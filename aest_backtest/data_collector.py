"""
DataCollector — DB에서 캔들 조회 → 지표 계산 (서버 호출 없음)

데이터 소스:
  일봉  → 기존 stock_info.daily_candles (AestDB.get_daily)
  분봉  → aest_db.candle_minute 캐시   (AestDB.get_minute)
  종목  → stock_information.stock_base_info (AestDB.get_stock_by_code)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta
from dataclasses import dataclass
from typing import Optional
from aest_db import AestDB


@dataclass
class StockDayData:
    code: str
    name: str
    capture_date: date
    market_cap: int = 0
    prev_open: int = 0
    prev_high: int = 0
    prev_low: int = 0
    prev_close: int = 0
    prev_volume: int = 0
    today_open: int = 0
    price_0905: int = 0
    volume_5min: int = 0
    amount_5min: int = 0
    gap_pct: float = 0.0
    early_move_pct: float = 0.0
    upper_wick_ratio: float = 0.0
    vol_ratio_5d: float = 0.0
    close_position: float = 0.0
    bearish_count: int = 0
    avg_volume_5d: int = 0


class DataCollector:

    def __init__(self, db: AestDB = None):
        self.db = db or AestDB()

    def collect(self, code: str, capture_date: date) -> Optional[StockDayData]:
        """DB 캔들만으로 지표 계산. 서버 호출 없음."""

        # ── 종목 정보 ──
        master = self.db.get_stock_by_code(code)
        name = master["name"] if master else code
        mkt_cap = master.get("market_cap", 0) if master else 0

        # ── 일봉 (기존 stock_info.daily_candles) ──
        dt_from = capture_date - timedelta(days=20)
        daily = self.db.get_daily(code, dt_from, capture_date)
        if len(daily) < 2:
            return None

        daily.sort(key=lambda x: x["dt"])
        prev_rows = [d for d in daily if d["dt"] < capture_date]
        if not prev_rows:
            return None

        prev = prev_rows[-1]       # 직전 거래일
        last5 = prev_rows[-5:]     # 최근 5거래일

        # ── 분봉 09:00~09:05 (aest_db.candle_minute 캐시) ──
        minutes = self.db.get_minute(code, capture_date, "09:00:00", "09:05:00")

        if minutes:
            today_open = minutes[0]["open"]
            price_0905 = minutes[-1]["close"]
            vol_5min = sum(m["volume"] for m in minutes)
            amt_5min = sum(m["volume"] * m["close"] for m in minutes)
        else:
            # 분봉이 없으면 당일 일봉 시가로 대체
            today_candle = [d for d in daily if d["dt"] == capture_date]
            if today_candle:
                today_open = today_candle[0]["open"]
                price_0905 = today_candle[0]["open"]
            else:
                return None
            vol_5min = 0
            amt_5min = 0

        # ── 지표 계산 ──
        prev_close = prev["close"]
        prev_range = (prev["high"] - prev["low"]) or 1

        # 갭률
        gap_pct = (today_open - prev_close) / prev_close * 100 if prev_close else 0

        # 초반 등락률 (09:00 → 09:05)
        early_pct = (price_0905 - today_open) / today_open * 100 if today_open else 0

        # 전일 윗꼬리 비율
        wick = prev["high"] - max(prev["open"], prev["close"])
        wick_ratio = wick / prev_range

        # 전일 거래량 / 5일 평균 거래량
        avg5 = (sum(d["volume"] for d in last5) / len(last5)) if last5 else 1
        vol_ratio = prev["volume"] / avg5 if avg5 else 1

        # 전일 종가 위치 (0=저가, 1=고가)
        close_pos = (prev["close"] - prev["low"]) / prev_range

        # 09:00~09:05 음봉 수
        bearish = sum(1 for m in minutes if m["close"] < m["open"])

        return StockDayData(
            code=code,
            name=name,
            capture_date=capture_date,
            market_cap=mkt_cap,
            prev_open=prev["open"],
            prev_high=prev["high"],
            prev_low=prev["low"],
            prev_close=prev_close,
            prev_volume=prev["volume"],
            today_open=today_open,
            price_0905=price_0905,
            volume_5min=vol_5min,
            amount_5min=amt_5min,
            gap_pct=round(gap_pct, 2),
            early_move_pct=round(early_pct, 2),
            upper_wick_ratio=round(wick_ratio, 3),
            vol_ratio_5d=round(vol_ratio, 2),
            close_position=round(close_pos, 3),
            bearish_count=bearish,
            avg_volume_5d=int(avg5),
        )
