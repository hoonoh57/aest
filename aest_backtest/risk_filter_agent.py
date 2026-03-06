"""
RiskFilterAgent — Layer 1 (DB 캔들 기반 위험 필터)

8개 룰로 위험점수 0~100 산출 → BLOCK / CAUTION / PASS 판정
목적: 폭락 종목(지뢰)을 사전에 제거
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import dataclass, field
from typing import List, Tuple, Dict
from aest_config import THRESHOLDS


@dataclass
class RiskScore:
    total: int = 0
    verdict: str = "PASS"
    scores: Dict[str, int] = field(default_factory=dict)
    evidence: List[Tuple[str, int, str]] = field(default_factory=list)


class RiskFilterAgent:

    def __init__(self, thresholds=None):
        self.th = thresholds or THRESHOLDS

    def evaluate(self, d) -> RiskScore:
        """StockDayData → RiskScore"""
        rs = RiskScore()

        # 1) 5분 거래대금 부족
        if d.amount_5min < self.th["vol_5min_danger"]:
            self._add(rs, "volume", 30,
                      f"5분거래대금 {d.amount_5min/1e8:.1f}억 < 1억")
        elif d.amount_5min < self.th["vol_5min_warning"]:
            self._add(rs, "volume", 15,
                      f"5분거래대금 {d.amount_5min/1e8:.1f}억 < 3억")

        # 2) 과대 갭
        if abs(d.gap_pct) >= self.th["gap_huge"]:
            self._add(rs, "gap", 25,
                      f"갭 {d.gap_pct:+.1f}% ≥ 10%")
        elif abs(d.gap_pct) >= self.th["gap_large"]:
            self._add(rs, "gap", 10,
                      f"갭 {d.gap_pct:+.1f}% ≥ 7%")

        # 3) 초반 급등
        if d.early_move_pct >= self.th["early_move_danger"]:
            self._add(rs, "early_move", 25,
                      f"초반등락 {d.early_move_pct:+.1f}% ≥ 8%")
        elif d.early_move_pct >= self.th["early_move_warning"]:
            self._add(rs, "early_move", 10,
                      f"초반등락 {d.early_move_pct:+.1f}% ≥ 5%")

        # 4) 소형주
        if 0 < d.market_cap < self.th["tiny_cap"]:
            self._add(rs, "market_cap", 15,
                      f"시총 {d.market_cap/1e8:.0f}억 < 500억")

        # 5) 전일 윗꼬리
        if d.upper_wick_ratio >= self.th["wick_ratio_danger"]:
            self._add(rs, "wick", 10,
                      f"전일윗꼬리 {d.upper_wick_ratio:.2f} ≥ 0.5")

        # 6) 거래량 폭증 + 갭
        if d.vol_ratio_5d >= self.th["vol_ratio_spike"] and d.gap_pct >= 3.0:
            self._add(rs, "vol_ratio", 15,
                      f"전일거래량 {d.vol_ratio_5d:.1f}배 & 갭 {d.gap_pct:+.1f}%")

        # 7) 전일 종가 저위치
        if d.close_position <= self.th["close_pos_low"]:
            self._add(rs, "close_pos", 10,
                      f"전일종가위치 {d.close_position:.2f} ≤ 0.2")

        # 8) 연속 음봉
        if d.bearish_count >= self.th["bearish_count"]:
            self._add(rs, "bearish", 10,
                      f"5분봉음봉 {d.bearish_count}개 ≥ 4")

        # 판정
        rs.total = min(rs.total, 100)
        if rs.total >= self.th["block_threshold"]:
            rs.verdict = "BLOCK"
        elif rs.total >= self.th["caution_threshold"]:
            rs.verdict = "CAUTION"
        else:
            rs.verdict = "PASS"

        return rs

    def _add(self, rs, key, score, reason):
        rs.scores[key] = score
        rs.total += score
        rs.evidence.append((key, score, reason))
