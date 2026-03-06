"""
risk_filter_agent.py  ─  Layer-1 매크로 위험 필터 (AND 방식 + 마켓 모드)
========================================================================
키움 조건식으로 포착된 종목 중, 필수 조건을 모두 통과해야 PASS.

마켓 모드
---------
  CRISIS    : 사이드카/폭락 반등 → F5(종가위치), F6(괴리율) 해제
  NORMAL    : 평시 → 7개 AND 필터 전체 적용
  OVERHEAT  : 과열장 → 7개 AND 필터 + PASS만 매매

필터 조건
---------
  F1  갭상승 < 10%           (과열 차단)          — 항상 적용
  F2  5분 거래대금 ≥ 10억     (유동성 확보)        — 항상 적용
  F3  전일 윗꼬리비 < 0.5     (매도압력 배제)      — 항상 적용
  F4  연속음봉 < 3일          (하락추세 배제)      — 항상 적용
  F5  전일 종가위치 0.3~0.8   (극단 캔들 배제)    — CRISIS 시 해제
  F6  5일 고점 괴리율 > -8%   (급락 후 반등 배제) — CRISIS 시 해제
  F7  5분 거래대금 < 300억     (과열 거래 배제)    — 항상 적용

판정
----
  모든 활성 필터 통과 → PASS
  1개 실패            → CAUTION
  2개+ 실패           → BLOCK
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Set
from aest_config import THRESHOLDS


# ──────────────────────────────────────────────
#  마켓 모드 상수
# ──────────────────────────────────────────────
MARKET_CRISIS = "CRISIS"
MARKET_NORMAL = "NORMAL"
MARKET_OVERHEAT = "OVERHEAT"

# CRISIS 모드에서 해제되는 필터
CRISIS_SKIP_FILTERS: Set[str] = {"F5_cpos", "F6_div5d"}


# ──────────────────────────────────────────────
#  RiskScore  데이터 클래스
# ──────────────────────────────────────────────
@dataclass
class RiskScore:
    total_fails: int = 0
    verdict: str = "PASS"               # PASS | CAUTION | BLOCK
    market_mode: str = MARKET_NORMAL
    passed: Dict[str, bool] = field(default_factory=dict)
    skipped: Dict[str, bool] = field(default_factory=dict)
    evidence: List[Tuple[str, bool, str]] = field(default_factory=list)

    def summary(self) -> str:
        """사람이 읽을 수 있는 판정 요약"""
        status = "✓" if self.verdict == "PASS" else "✗"
        parts = [f"{status} [{self.verdict}] 실패={self.total_fails} 모드={self.market_mode}"]
        for key, ok, reason in self.evidence:
            if key in self.skipped:
                mark = "  ○"  # 해제됨
            elif ok:
                mark = "  ✓"
            else:
                mark = "  ✗"
            parts.append(f"{mark} {reason}")
        return "\n".join(parts)


# ──────────────────────────────────────────────
#  RiskFilterAgent  (AND 필터 + 마켓 모드)
# ──────────────────────────────────────────────
class RiskFilterAgent:
    """Layer-1 매크로 위험 필터 에이전트"""

    def __init__(self, thresholds: Optional[Dict] = None):
        th = thresholds or THRESHOLDS
        self.th = {
            "gap_max": th.get("gap_max", 10.0),
            "min_amount_5min": th.get("min_amount_5min", 10.0),
            "max_wick": th.get("max_wick", 0.5),
            "max_bearish": th.get("max_bearish", 3),
            "cpos_low": th.get("cpos_low", 0.3),
            "cpos_high": th.get("cpos_high", 0.8),
            "min_div_5d": th.get("min_div_5d", -8.0),
            "max_amount_5min": th.get("max_amount_5min", 300.0),
        }
        self._market_mode = MARKET_NORMAL

    # ──────────────────────────────────────────
    #  마켓 모드 설정
    # ──────────────────────────────────────────
    def set_market_mode(self, mode: str):
        """
        장 시작 후 지수 확인 결과로 마켓 모드를 설정한다.

        Parameters
        ----------
        mode : str
            "CRISIS"   — 사이드카/폭락 반등 (F5, F6 해제)
            "NORMAL"   — 평시 (7개 전체 적용)
            "OVERHEAT" — 과열장 (7개 전체 + PASS만 매매)
        """
        if mode not in (MARKET_CRISIS, MARKET_NORMAL, MARKET_OVERHEAT):
            raise ValueError(f"Unknown market mode: {mode}")
        self._market_mode = mode

    @property
    def market_mode(self) -> str:
        return self._market_mode

    def evaluate(self, d) -> RiskScore:
        """
        StockDayData 객체를 받아 AND 필터를 적용한다.
        마켓 모드에 따라 일부 필터가 해제될 수 있다.

        Parameters
        ----------
        d : StockDayData
            data_collector.collect() 가 반환한 종목별 데이터

        Returns
        -------
        RiskScore
        """
        rs = RiskScore()
        rs.market_mode = self._market_mode

        # CRISIS 모드에서 해제할 필터 목록
        skip = CRISIS_SKIP_FILTERS if self._market_mode == MARKET_CRISIS else set()

        # ─── 메트릭 추출 (None 안전 처리) ───
        gap = d.gap_pct if d.gap_pct is not None else 0.0
        wick = d.upper_wick_ratio if d.upper_wick_ratio is not None else 0.0
        cpos = d.close_position if d.close_position is not None else 0.5
        bearish = d.bearish_count if d.bearish_count is not None else 0
        div_5d = d.divergence_5d if d.divergence_5d is not None else 0.0
        amt = self._get_amount_eok(d)

        # ═══════════════════════════════════════════
        # F1: 갭상승 < 10%
        # ═══════════════════════════════════════════
        f1 = gap < self.th["gap_max"]
        self._check(rs, "F1_gap", f1, skip,
                    f"갭 {gap:+.1f}% {'<' if f1 else '>='} {self.th['gap_max']}%")

        # ═══════════════════════════════════════════
        # F2: 5분 거래대금 ≥ 10억
        # ═══════════════════════════════════════════
        f2 = amt >= self.th["min_amount_5min"]
        self._check(rs, "F2_liquidity", f2, skip,
                    f"5분대금 {amt:.1f}억 {'≥' if f2 else '<'} {self.th['min_amount_5min']}억")

        # ═══════════════════════════════════════════
        # F3: 전일 윗꼬리비 < 0.5
        # ═══════════════════════════════════════════
        f3 = wick < self.th["max_wick"]
        self._check(rs, "F3_wick", f3, skip,
                    f"윗꼬리비 {wick:.2f} {'<' if f3 else '>='} {self.th['max_wick']}")

        # ═══════════════════════════════════════════
        # F4: 연속음봉 < 3일
        # ═══════════════════════════════════════════
        f4 = bearish < self.th["max_bearish"]
        self._check(rs, "F4_bearish", f4, skip,
                    f"연속음봉 {bearish}일 {'<' if f4 else '>='} {self.th['max_bearish']}일")

        # ═══════════════════════════════════════════
        # F5: 종가위치 0.3 ~ 0.8  (CRISIS 시 해제)
        # ═══════════════════════════════════════════
        f5 = self.th["cpos_low"] < cpos < self.th["cpos_high"]
        self._check(rs, "F5_cpos", f5, skip,
                    f"종가위치 {cpos:.2f} {'∈' if f5 else '∉'} ({self.th['cpos_low']}, {self.th['cpos_high']})")

        # ═══════════════════════════════════════════
        # F6: 5일 고점 괴리율 > -8%  (CRISIS 시 해제)
        # ═══════════════════════════════════════════
        f6 = div_5d > self.th["min_div_5d"]
        self._check(rs, "F6_div5d", f6, skip,
                    f"5일괴리 {div_5d:+.1f}% {'>' if f6 else '<='} {self.th['min_div_5d']}%")

        # ═══════════════════════════════════════════
        # F7: 과열 거래대금 < 300억
        # ═══════════════════════════════════════════
        f7 = amt < self.th["max_amount_5min"]
        self._check(rs, "F7_overheat", f7, skip,
                    f"5분대금 {amt:.1f}억 {'<' if f7 else '>='} {self.th['max_amount_5min']}억")

        # ═══════════════════════════════════════════
        # 최종 판정
        # ═══════════════════════════════════════════
        if rs.total_fails == 0:
            rs.verdict = "PASS"
        elif rs.total_fails == 1:
            rs.verdict = "CAUTION"
        else:
            rs.verdict = "BLOCK"

        return rs

    # ──────────────────────────────────────────
    #  Helpers
    # ──────────────────────────────────────────
    def _get_amount_eok(self, d) -> float:
        """5분 거래대금을 억 단위로 반환"""
        if d.amount_5min and d.amount_5min > 0:
            return d.amount_5min / 1e8
        if d.est_5min_amount and d.est_5min_amount > 0:
            return d.est_5min_amount
        return 0.0

    def _check(self, rs: RiskScore, key: str, ok: bool, skip: set, reason: str):
        """
        조건 통과/실패를 기록한다.
        skip 집합에 포함된 필터는 실패해도 카운트하지 않는다.
        """
        if key in skip:
            # 해제된 필터: 기록은 하되 실패 카운트 안 함
            rs.skipped[key] = True
            rs.passed[key] = ok  # 실제 결과는 기록
            suffix = " [해제]" if not ok else ""
            rs.evidence.append((key, ok, reason + suffix))
        else:
            rs.passed[key] = ok
            if not ok:
                rs.total_fails += 1
            rs.evidence.append((key, ok, reason))
