"""
risk_filter_agent.py  ─  Layer-1 매크로 위험 필터 (09:00~09:05 기준)
========================================================================
키움 조건식으로 포착된 종목 중 매크로적 위험 요인을 점수화하여
PASS / CAUTION / BLOCK 판정을 내린다.

설계 원칙
---------
- 갭상승 ≥10% → 무조건 BLOCK (100점, 즉시 반환)
- 그 외 8개 규칙의 누적 점수로 판정
- AEST / SuperTrend / JMA 등 실시간 기술지표는 Layer-2(매매 로직)에서 처리
- 이 에이전트는 "확실히 나쁜 종목"만 걸러내는 역할

점수 기준
---------
  0~19  →  PASS     (매매 후보)
 20~34  →  CAUTION  (주의, 모니터링만)
 35~100 →  BLOCK    (매매 제외)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from aest_config import THRESHOLDS


# ──────────────────────────────────────────────
#  RiskScore  데이터 클래스
# ──────────────────────────────────────────────
@dataclass
class RiskScore:
    total: int = 0
    verdict: str = "PASS"               # PASS | CAUTION | BLOCK
    scores: Dict[str, int] = field(default_factory=dict)
    evidence: List[Tuple[str, int, str]] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"위험={self.total} [{self.verdict}]"]
        for key, score, reason in self.evidence:
            parts.append(f"  +{score:2d} {reason}")
        return "\n".join(parts)


# ──────────────────────────────────────────────
#  RiskFilterAgent
# ──────────────────────────────────────────────
class RiskFilterAgent:
    """Layer-1 매크로 위험 필터 에이전트"""

    def __init__(self, thresholds: Optional[Dict] = None):
        th = thresholds or THRESHOLDS
        self.th = {
            # ── 판정 경계 ──
            "block_threshold": th.get("block_threshold", 35),
            "caution_threshold": th.get("caution_threshold", 20),

            # ── 규칙별 임계값 ──
            "gap_huge": th.get("gap_huge", 10.0),        # 갭 ≥10% → BLOCK
            "gap_large": th.get("gap_large", 7.0),       # 갭 ≥7%  → +15
            "gap_mid": th.get("gap_mid", 4.0),           # 갭 ≥4%  → +5
            "vol5_low": th.get("vol5_low", 1.0),         # 5분 거래대금 < 1억 → +30
            "vol5_warn": th.get("vol5_warn", 10.0),      # 5분 거래대금 < 10억 → +10
            "early_move_high": th.get("early_move_high", 5.0),  # 초기상승 ≥5% → +10
            "mcap_low": th.get("mcap_low", 500),         # 시가총액 < 500억 → +10
            "wick_high": th.get("wick_high", 0.6),       # 윗꼬리비 ≥0.6 → +10
            "vol_ratio_high": th.get("vol_ratio_high", 3.0),   # 거래량비 ≥3.0 + 갭≥3% → +10
            "close_pos_low": th.get("close_pos_low", 0.2),     # 종가위치 ≤0.2 → +10
            "close_pos_high": th.get("close_pos_high", 0.9),   # 종가위치 ≥0.9 → +10
            "bearish_count": th.get("bearish_count", 3),        # 연속음봉 ≥3 → +10
        }

    def evaluate(self, d) -> RiskScore:
        """
        StockDayData 객체를 받아 위험 점수를 산출한다.

        Parameters
        ----------
        d : StockDayData
            data_collector.collect() 가 반환한 종목별 데이터

        Returns
        -------
        RiskScore
        """
        rs = RiskScore()

        # ═══════════════════════════════════════════
        # Rule 1: 갭상승 ≥10% → 무조건 BLOCK
        # ═══════════════════════════════════════════
        if d.gap_pct >= self.th["gap_huge"]:
            self._add(rs, "gap_block", 100,
                      f"갭 {d.gap_pct:+.1f}% >= {self.th['gap_huge']}% 무조건 BLOCK")
            rs.total = 100
            rs.verdict = "BLOCK"
            return rs

        # ═══════════════════════════════════════════
        # Rule 2: 5분 거래대금 부족
        # ═══════════════════════════════════════════
        amount_eok = d.amount_5min / 1e8 if d.amount_5min else 0
        if amount_eok < self.th["vol5_low"]:
            self._add(rs, "vol5_zero", 30,
                      f"5분 거래대금 {amount_eok:.1f}억 < {self.th['vol5_low']}억 (유동성 없음)")
        elif amount_eok < self.th["vol5_warn"]:
            self._add(rs, "vol5_low", 10,
                      f"5분 거래대금 {amount_eok:.1f}억 < {self.th['vol5_warn']}억")

        # ═══════════════════════════════════════════
        # Rule 3: 갭 경고 (4%~10%)
        # ═══════════════════════════════════════════
        if d.gap_pct >= self.th["gap_large"]:
            self._add(rs, "gap_warn", 15,
                      f"갭 {d.gap_pct:+.1f}% >= {self.th['gap_large']}%")
        elif d.gap_pct >= self.th["gap_mid"]:
            self._add(rs, "gap_mid", 5,
                      f"갭 {d.gap_pct:+.1f}% >= {self.th['gap_mid']}%")

        # ═══════════════════════════════════════════
        # Rule 4: 초기 급등
        # ═══════════════════════════════════════════
        if d.early_move_pct >= self.th["early_move_high"]:
            self._add(rs, "early_spike", 10,
                      f"09:05 상승 {d.early_move_pct:+.1f}% >= {self.th['early_move_high']}%")

        # ═══════════════════════════════════════════
        # Rule 5: 소형주 (시가총액 < 500억)
        # ═══════════════════════════════════════════
        if d.market_cap and d.market_cap < self.th["mcap_low"]:
            self._add(rs, "tiny_cap", 10,
                      f"시총 {d.market_cap}억 < {self.th['mcap_low']}억")

        # ═══════════════════════════════════════════
        # Rule 6: 전일 윗꼬리 비율
        # ═══════════════════════════════════════════
        if d.upper_wick_ratio >= self.th["wick_high"]:
            self._add(rs, "wick", 10,
                      f"전일 윗꼬리비 {d.upper_wick_ratio:.2f} >= {self.th['wick_high']}")

        # ═══════════════════════════════════════════
        # Rule 7: 거래량 급등 + 갭 동반
        # ═══════════════════════════════════════════
        if d.vol_ratio_5d >= self.th["vol_ratio_high"] and d.gap_pct >= 3.0:
            self._add(rs, "vol_gap", 10,
                      f"거래량비 {d.vol_ratio_5d:.1f}x + 갭 {d.gap_pct:+.1f}%")

        # ═══════════════════════════════════════════
        # Rule 8: 전일 종가 위치
        # ═══════════════════════════════════════════
        if d.close_position <= self.th["close_pos_low"]:
            self._add(rs, "close_low", 10,
                      f"전일 종가위치 {d.close_position:.2f} <= {self.th['close_pos_low']} (하단)")
        elif d.close_position >= self.th["close_pos_high"]:
            self._add(rs, "close_high", 10,
                      f"전일 종가위치 {d.close_position:.2f} >= {self.th['close_pos_high']} (상단 매물압력)")

        # ═══════════════════════════════════════════
        # Rule 9: 연속 음봉
        # ═══════════════════════════════════════════
        if d.bearish_count >= self.th["bearish_count"]:
            self._add(rs, "bearish", 10,
                      f"연속음봉 {d.bearish_count}일 >= {self.th['bearish_count']}일")

        # ═══════════════════════════════════════════
        # 최종 판정
        # ═══════════════════════════════════════════
        rs.total = min(rs.total, 100)

        if rs.total >= self.th["block_threshold"]:
            rs.verdict = "BLOCK"
        elif rs.total >= self.th["caution_threshold"]:
            rs.verdict = "CAUTION"
        else:
            rs.verdict = "PASS"

        return rs

    # ──────────────────────────────────────────
    #  Helper
    # ──────────────────────────────────────────
    def _add(self, rs: RiskScore, key: str, score: int, reason: str):
        """점수 추가 및 근거 기록"""
        rs.scores[key] = score
        rs.total += score
        rs.evidence.append((key, score, reason))
