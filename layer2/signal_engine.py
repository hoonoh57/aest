"""
layer2/signal_engine.py — 분봉 수신 + 표준 지표 계산 + Signal 생성
"""

import numpy as np
import pandas as pd
from core import (ServerClient, compute_supertrend, compute_aest,
                  compute_jma_trend, compute_tick_intensity)
from filters import FILTER_REGISTRY
from strategies.base import Signal


class SignalEngine:
    """
    종목별 분봉을 수신하고 표준 지표를 계산하여
    Signal 객체를 생성한다.
    """

    def __init__(self, host="localhost", port=8082,
                 atr_len=14, mult=3.0,
                 filter_name="LonesomeTheBlue",
                 tick_size=30):
        self.client = ServerClient(host, port)
        self.atr_len = atr_len
        self.mult = mult
        self.filter_func = FILTER_REGISTRY.get(filter_name,
                                                FILTER_REGISTRY["None"])
        self.tick_size = tick_size

        # 종목별 캐시
        self._cache = {}   # code -> {tf, df, today_open, prev_signals}

    def initialize(self, code: str, tf: str, date_str: str = "",
                   market: str = "KOSDAQ"):
        """종목 초기화: 분봉 다운로드 + 지표 계산"""
        tf_min = int(tf.replace("m", "")) if tf.startswith("m") else 1
        df = self.client.minute_candles_from(code, tick=tf_min,
                                              from_date=date_str)
        df = compute_supertrend(df, self.atr_len, self.mult)
        df = compute_aest(df, self.atr_len, self.mult, self.filter_func)
        df = compute_jma_trend(df, length=7, phase=50, power=2)

        # ATR 계산 (AEST 내부의 EMA ATR 재현)
        h = df["high"].values.astype(float)
        l = df["low"].values.astype(float)
        c = df["close"].values.astype(float)
        n = len(df)
        tr = np.zeros(n)
        tr[0] = h[0] - l[0]
        for i in range(1, n):
            tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]),
                        abs(l[i] - c[i-1]))
        alpha = 2.0 / (self.atr_len + 1)
        eatr = np.zeros(n)
        eatr[0] = tr[0]
        for i in range(1, n):
            eatr[i] = alpha * tr[i] + (1 - alpha) * eatr[i-1]
        df["atr"] = eatr

        # 당일 시초가
        today_open = float(df.iloc[-1]["open"])
        if date_str:
            day_mask = df.index >= pd.Timestamp(date_str)
            day_df = df[day_mask]
            if len(day_df) > 0:
                today_open = float(day_df.iloc[0]["open"])

        self._cache[code] = {
            "tf": tf,
            "df": df,
            "today_open": today_open,
            "market": market,
        }
        return df

    def refresh(self, code: str, date_str: str = ""):
        """최신 봉 갱신"""
        cache = self._cache.get(code)
        if not cache:
            return None
        return self.initialize(code, cache["tf"], date_str,
                               cache["market"])

    def get_signal(self, code: str, bar_index: int = -1) -> Signal:
        """특정 봉의 Signal 객체 생성"""
        cache = self._cache.get(code)
        if not cache:
            raise ValueError(f"종목 {code} 미초기화")

        df = cache["df"]
        idx = bar_index
        row = df.iloc[idx]
        prev = df.iloc[idx - 1] if abs(idx) < len(df) else row

        # 연속 양봉 계산
        consec = 0
        for i in range(len(df) + idx, 0, -1):
            r = df.iloc[i]
            if r["close"] > r["open"]:
                consec += 1
            else:
                break

        # 현재봉 상승률
        candle_rise = 0.0
        if prev["close"] > 0:
            candle_rise = ((row["close"] - prev["close"])
                          / prev["close"] * 100)

        return Signal(
            timestamp=str(df.index[idx]),
            close=float(row["close"]),
            open_price=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            aest_trend=int(row.get("aest_trend", 0)),
            aest_line=float(row.get("aest_line", 0)),
            st_trend=int(row.get("st_trend", 0)),
            st_line=float(row.get("st_line", 0)),
            jma_trend=int(row.get("jma_trend", 0)),
            jma_line=float(row.get("jma_line", 0)),
            atr=float(row.get("atr", 0)),
            tick_intensity=int(row.get("tick_intensity", 0)),
            tick_ma5=float(row.get("tick_ma5", 0) or 0),
            tick_ma20=float(row.get("tick_ma20", 0) or 0),
            today_open=cache["today_open"],
            prev_close=float(prev["close"]),
            prev_jma_trend=int(prev.get("jma_trend", 0)),
            prev_st_trend=int(prev.get("st_trend", 0)),
            consecutive_bull=consec,
            candle_rise=candle_rise,
            market=cache["market"],
        )

    def get_all_signals(self, code: str, start_idx: int = 0):
        """전체 봉에 대한 Signal 리스트 (백테스트용)"""
        cache = self._cache.get(code)
        if not cache:
            raise ValueError(f"종목 {code} 미초기화")
        df = cache["df"]
        signals = []
        for i in range(max(1, start_idx), len(df)):
            signals.append(self.get_signal(code, i))
        return signals
