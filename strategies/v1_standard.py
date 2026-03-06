"""
strategies/v1_standard.py — 기본 매매 로직 v1.0
══════════════════════════════════════════════════
  이 파일은 절대 수정하지 않는다.
  변형이 필요하면 v2_xxx.py 를 새로 만든다.

  매수: AEST=+1 AND ST=+1 전제
        + JMA J↑ OR 단일봉>ATR×0.5 OR 3연속양봉
        + 안전장치 (동적VI, 정적VI, 추격매수차단)

  매도: 1순위 가격<AEST라인 (비상)
        2순위 ST하락전환
        3순위 수익≥1% + JMA J↓

  2026-03-06 확정. 이후 수정 금지.
"""

from typing import Optional
from strategies.base import BaseStrategy, Signal, ExitReason


class V1Standard(BaseStrategy):

    def __init__(self, params: dict = None):
        p = params or {}
        self._p = {
            # 매수 전제
            "entry_aest": 1,
            "entry_st": 1,

            # 트리거
            "atr_candle_mult": 0.5,      # 단일봉 상승 > ATR × 0.5
            "consecutive_bull": 3,        # 연속 양봉 수

            # 안전장치
            "vi_dynamic_kospi": 3.0,      # 코스피 동적VI (%)
            "vi_dynamic_kosdaq": 6.0,     # 코스닥 동적VI (%)
            "vi_static_max": 8.0,         # 시초가 대비 상한 (%)
            "chase_atr_mult": 2.0,        # 추격매수 차단 ATR 배수

            # 매도
            "profit_exit_min": 1.0,       # 익절 최소 수익률 (%)
        }
        self._p.update(p)

    @property
    def name(self) -> str:
        return "v1_standard"

    @property
    def version(self) -> str:
        return "1.0.0"

    def get_params(self) -> dict:
        return self._p.copy()

    # ══════════════════════════════════════════
    #  매수 판단
    # ══════════════════════════════════════════
    def should_buy(self, s: Signal) -> bool:
        # ── 전제: AEST=+1 AND ST=+1 ──
        if s.aest_trend != self._p["entry_aest"]:
            return False
        if s.st_trend != self._p["entry_st"]:
            return False

        # ── 트리거 (OR) ──
        trigger = False

        # 1) JMA J↑ (전봉 ≤0 → 현재 +1)
        if s.prev_jma_trend <= 0 and s.jma_trend == 1:
            trigger = True

        # 2) 단일봉 양봉 > ATR × 0.5
        if s.atr > 0 and (s.close - s.open_price) > s.atr * self._p["atr_candle_mult"]:
            trigger = True

        # 3) 3연속 양봉
        if s.consecutive_bull >= self._p["consecutive_bull"]:
            trigger = True

        if not trigger:
            return False

        # ── 안전장치 (AND, 모두 통과) ──

        # 1) 동적 VI 회피
        vi_limit = (self._p["vi_dynamic_kospi"]
                    if s.market == "KOSPI"
                    else self._p["vi_dynamic_kosdaq"])
        if s.candle_rise >= vi_limit:
            return False

        # 2) 정적 VI 회피
        if s.today_open > 0:
            rise_from_open = (s.close - s.today_open) / s.today_open * 100
            if rise_from_open >= self._p["vi_static_max"]:
                return False

        # 3) 추격매수 차단
        if s.atr > 0 and s.aest_line > 0:
            max_chase = s.aest_line + s.atr * self._p["chase_atr_mult"]
            if s.close > max_chase:
                return False

        return True

    # ══════════════════════════════════════════
    #  매도 판단
    # ══════════════════════════════════════════
    def should_sell(self, s: Signal, entry_price: float,
                    current_pnl_pct: float) -> Optional[ExitReason]:

        # ── 1순위: 비상 (가격 < AEST 라인) ──
        if s.aest_line > 0 and s.close < s.aest_line:
            return ExitReason.EMERGENCY_AEST

        # ── 2순위: ST 하락전환 ──
        if s.st_trend == -1 and s.prev_st_trend == 1:
            return ExitReason.ST_REVERSAL

        # ── 3순위: 익절 (수익 ≥ 1% + JMA J↓) ──
        if current_pnl_pct >= self._p["profit_exit_min"]:
            if s.prev_jma_trend == 1 and s.jma_trend <= 0:
                return ExitReason.PROFIT_JMA

        return None  # 홀딩
