#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.py — 불변 로직
  - ServerClient (server32 API)
  - Standard SuperTrend
  - AEST 계산 엔진 (필터 주입 방식)
  - JMA (Jurik Moving Average)
  - 틱강도 (Tick Intensity)
  - HTML 차트 생성
"""

import json
import numpy as np
import pandas as pd
import requests
from datetime import datetime, timedelta


# ═══════════════════════════════════════════════════════════════
#  서버 클라이언트  (server32 매뉴얼 준수)
# ═══════════════════════════════════════════════════════════════
class ServerClient:
    """
    server32 REST API
    응답: { "Success": bool, "Message": str, "Data": ... }
    """

    def __init__(self, host="localhost", port=8082):
        self.base = f"http://{host}:{port}"

    def _get(self, path, params=None):
        r = requests.get(f"{self.base}{path}", params=params, timeout=30)
        r.raise_for_status()
        js = r.json()
        if not js.get("Success"):
            raise RuntimeError(f"API: {js.get('Message', 'unknown')}")
        return js["Data"]

    def symbol_name(self, code):
        try:
            return self._get("/api/market/symbol", {"code": code}).get("name", code)
        except Exception:
            return code

    def daily_candles(self, code, years=5):
        now = datetime.now()
        data = self._get("/api/market/candles/daily", {
            "code": code,
            "date": now.strftime("%Y%m%d"),
            "stopDate": (now - timedelta(days=365 * years)).strftime("%Y%m%d"),
        })
        if not data:
            raise RuntimeError("일봉 데이터 없음")
        rows = []
        for d in data:
            rows.append({
                "date":   pd.to_datetime(str(d["일자"])),
                "open":   abs(int(d["시가"])),
                "high":   abs(int(d["고가"])),
                "low":    abs(int(d["저가"])),
                "close":  abs(int(d.get("현재가", d.get("종가", 0)))),
                "volume": abs(int(d["거래량"])),
            })
        df = pd.DataFrame(rows).sort_values("date").set_index("date")
        df = df[df["volume"] > 0]
        print(f"  {len(df)}봉 로드 ({df.index[0]} ~ {df.index[-1]})")
        return df

    def minute_candles(self, code, tick=1):
        stop = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d") + "090000"
        data = self._get("/api/market/candles/minute", {
            "code": code, "tick": tick, "stopTime": stop,
        })
        if not data:
            raise RuntimeError("분봉 데이터 없음")
        rows = []
        for d in data:
            rows.append({
                "date":   pd.to_datetime(str(d["체결시간"])),
                "open":   abs(int(d["시가"])),
                "high":   abs(int(d["고가"])),
                "low":    abs(int(d["저가"])),
                "close":  abs(int(d["현재가"])),
                "volume": abs(int(d["거래량"])),
            })
        df = pd.DataFrame(rows).sort_values("date").set_index("date")
        df = df[df["volume"] > 0]
        print(f"  {len(df)}봉 로드 ({df.index[0]} ~ {df.index[-1]})")
        return df

    def minute_candles_from(self, code, tick=1, from_date=""):
        """
        분봉: 특정 일자 ~ 현재
        from_date: "YYYY-MM-DD" or "YYYYMMDD"
        stopTime = from_date 09:00:00
        """
        if not from_date:
            return self.minute_candles(code, tick)

        d = from_date.replace("-", "")
        stop = d + "090000"

        print(f"  API: /api/market/candles/minute?code={code}&tick={tick}&stopTime={stop}")
        data = self._get("/api/market/candles/minute", {
            "code": code, "tick": tick, "stopTime": stop,
        })
        if not data:
            raise RuntimeError("분봉 데이터 없음")
        rows = []
        for d in data:
            rows.append({
                "date":   pd.to_datetime(str(d["체결시간"])),
                "open":   abs(int(d["시가"])),
                "high":   abs(int(d["고가"])),
                "low":    abs(int(d["저가"])),
                "close":  abs(int(d["현재가"])),
                "volume": abs(int(d["거래량"])),
            })
        df = pd.DataFrame(rows).sort_values("date").set_index("date")
        df = df[df["volume"] > 0]
        print(f"  {len(df)}봉 로드 ({df.index[0]} ~ {df.index[-1]})")
        return df

    def tick_candles(self, code, tick=30, stop_time=""):
        """
        틱캔들 조회
        tick: 틱 간격 (15, 30, 60, 120 등)
        stop_time: "YYYYMMDDHHmmss" — 이 시점까지 과거로 조회
        """
        if not stop_time:
            stop_time = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d") + "090000"

        print(f"  API: /api/market/candles/tick?code={code}&tick={tick}&stopTime={stop_time}")
        data = self._get("/api/market/candles/tick", {
            "code": code, "tick": tick, "stopTime": stop_time,
        })
        if not data:
            raise RuntimeError("틱캔들 데이터 없음")
        rows = []
        for d in data:
            rows.append({
                "date":   pd.to_datetime(str(d["체결시간"])),
                "open":   abs(int(d["시가"])),
                "high":   abs(int(d["고가"])),
                "low":    abs(int(d["저가"])),
                "close":  abs(int(d["현재가"])),
                "volume": abs(int(d["거래량"])),
            })
        df = pd.DataFrame(rows).sort_values("date").set_index("date")
        df = df[df["volume"] > 0]
        print(f"  틱캔들({tick}틱): {len(df)}개 로드 ({df.index[0]} ~ {df.index[-1]})")
        return df


# ═══════════════════════════════════════════════════════════════
#  Standard SuperTrend
# ═══════════════════════════════════════════════════════════════
def compute_supertrend(df, atr_len=14, mult=3.0):
    h, l, c = df["high"].values.astype(float), df["low"].values.astype(float), df["close"].values.astype(float)
    n = len(df)

    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))

    atr = np.full(n, np.nan)
    atr[atr_len - 1] = np.mean(tr[:atr_len])
    for i in range(atr_len, n):
        atr[i] = (atr[i-1] * (atr_len - 1) + tr[i]) / atr_len

    mid = (h + l) / 2.0
    upper, lower = mid + mult * atr, mid - mult * atr
    trend = np.ones(n)
    st_line = np.full(n, np.nan)

    for i in range(1, n):
        if np.isnan(atr[i]):
            continue
        if lower[i] < lower[i-1] and c[i-1] > lower[i-1]:
            lower[i] = lower[i-1]
        if upper[i] > upper[i-1] and c[i-1] < upper[i-1]:
            upper[i] = upper[i-1]
        if trend[i-1] == 1:
            trend[i] = -1 if c[i] < lower[i] else 1
        else:
            trend[i] = 1 if c[i] > upper[i] else -1
        st_line[i] = lower[i] if trend[i] == 1 else upper[i]

    df["st_line"] = st_line
    df["st_trend"] = trend
    return df


# ═══════════════════════════════════════════════════════════════
#  AEST 엔진 (횡보 필터 주입 방식)
# ═══════════════════════════════════════════════════════════════
def compute_aest(df, atr_len=14, mult=3.0, range_filter_func=None):
    """
    Adaptive SuperTrend — 횡보 필터 기반
    range_filter_func(df) → bool 배열 (True=횡보, False=추세)
    횡보 구간에서는 ST 전환을 차단
    """
    h, l, c = df["high"].values.astype(float), df["low"].values.astype(float), df["close"].values.astype(float)
    n = len(df)

    # EATR
    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
    alpha = 2.0 / (atr_len + 1)
    eatr = np.zeros(n)
    eatr[0] = tr[0]
    for i in range(1, n):
        eatr[i] = alpha * tr[i] + (1 - alpha) * eatr[i-1]

    mid = (h + l) / 2.0
    upper, lower = mid + mult * eatr, mid - mult * eatr

    # 횡보 판정
    if range_filter_func is not None:
        is_range = range_filter_func(df)
    else:
        is_range = np.zeros(n, dtype=bool)

    trend = np.ones(n)
    aest_line = np.full(n, np.nan)

    for i in range(1, n):
        if np.isnan(eatr[i]):
            continue

        # Lock bands
        if lower[i] < lower[i-1] and c[i-1] > lower[i-1]:
            lower[i] = lower[i-1]
        if upper[i] > upper[i-1] and c[i-1] < upper[i-1]:
            upper[i] = upper[i-1]

        # 추세 결정
        if is_range[i]:
            # 횡보 → 전환 차단
            trend[i] = trend[i-1]
        else:
            # 추세 → 정상 판단
            if trend[i-1] == 1:
                trend[i] = -1 if c[i] < lower[i] else 1
            else:
                trend[i] = 1 if c[i] > upper[i] else -1

        aest_line[i] = lower[i] if trend[i] == 1 else upper[i]

    df["aest_line"] = aest_line
    df["aest_trend"] = trend
    df["aest_is_range"] = is_range
    return df


# ═══════════════════════════════════════════════════════════════
#  JMA (Jurik Moving Average) — pandas_ta 원본 알고리즘
#   + 실시간 증분 계산 클래스
# ═══════════════════════════════════════════════════════════════
def _jma_static_params(length, phase):
    """JMA 정적 파라미터 계산 (배치/증분 공용)"""
    _length = max(int(length), 2)  # 최소 2 (half_len=0 방지)
    _phase = float(phase)
    half_len = 0.5 * (_length - 1)
    pr = 0.5 if _phase < -100 else 2.5 if _phase > 100 else 1.5 + _phase * 0.01
    length1 = max(np.log(np.sqrt(half_len)) / np.log(2.0) + 2.0, 0.0) if half_len > 0 else 2.0
    pow1 = max(length1 - 2.0, 0.5)
    length2 = length1 * np.sqrt(half_len) if half_len > 0 else 0.0
    bet = length2 / (length2 + 1.0) if (length2 + 1.0) != 0 else 0.0
    beta = 0.45 * (_length - 1) / (0.45 * (_length - 1) + 2.0)
    return _length, pr, length1, pow1, bet, beta


# ═══════════════════════════════════════════════════════════════
#  JMA (Jurik Moving Average) — VB.NET 원본 기반
#   + 실시간 증분 계산 클래스
#
#  핵심 파라미터:
#    length : 기간 (period)
#    phase  : 위상 [-100~100] → phaseRatio 0.5~2.5
#    power  : alpha 지수 — alpha = beta^power
#             power↑ → alpha↑ → 더 평탄 (노이즈 제거)
#             power↓ → alpha↓ → 더 민감 (빠른 추종)
# ═══════════════════════════════════════════════════════════════
def _jma_params(length, phase, power):
    """JMA 정적 파라미터 계산 (배치/증분 공용)"""
    _length = max(int(length), 2)
    _phase = float(phase)
    _power = int(power) if power is not None else 2

    if _phase < -100:
        phase_ratio = 0.5
    elif _phase > 100:
        phase_ratio = 2.5
    else:
        phase_ratio = _phase / 100.0 + 1.5

    beta = 0.45 * (_length - 1) / (0.45 * (_length - 1) + 2.0)
    alpha = beta ** _power  # ← power가 직접 alpha 결정

    return _length, phase_ratio, beta, alpha, _power


class JMAIncremental:
    """
    JMA 실시간 증분 계산기 — VB.NET 원본 알고리즘

    사용법:
        jma = JMAIncremental(length=7, phase=50, power=2)

        # 과거 데이터로 워밍업
        for price in historical_closes:
            val, trend = jma.update(price)

        # 실시간: 확정 봉
        val, trend = jma.update(new_close)

        # 미확정 봉 미리보기 (상태 불변)
        val, trend = jma.peek(current_price)
    """

    def __init__(self, length=7, phase=50, power=2):
        self._length, self._pr, self._beta, self._alpha, self._power = \
            _jma_params(length, phase, power)

        self._e0 = np.nan
        self._e1 = np.nan
        self._e2 = np.nan
        self._jma_val = np.nan
        self._prev_jma = np.nan
        self._trend = 0
        self._count = 0
        # lookback 평균용
        self._price_buffer = []

    def _save_state(self):
        return (self._e0, self._e1, self._e2,
                self._jma_val, self._prev_jma, self._trend,
                self._count, self._price_buffer.copy())

    def _restore_state(self, s):
        (self._e0, self._e1, self._e2,
         self._jma_val, self._prev_jma, self._trend,
         self._count, self._price_buffer) = s

    def _step(self, price):
        idx = self._count
        alpha = self._alpha
        beta = self._beta
        pr = self._pr

        # 초기화
        if np.isnan(self._e0):
            self._e0 = price
            self._e1 = 0.0
            self._e2 = 0.0
            self._prev_jma = price

        # 3단계 필터
        self._e0 = (1.0 - alpha) * price + alpha * self._e0
        self._e1 = (price - self._e0) * (1.0 - beta) + beta * self._e1
        self._e2 = ((self._e0 + pr * self._e1 - self._prev_jma)
                     * (1.0 - alpha) ** 2
                     + alpha ** 2 * self._e2)

        # lookback 기간: 단순평균 / 이후: JMA
        self._price_buffer.append(price)
        if idx < self._length:
            current_jma = sum(self._price_buffer) / len(self._price_buffer)
        else:
            current_jma = round(self._e2 + self._prev_jma, 1)

        # 추세 판정
        if not np.isnan(self._prev_jma) and idx > 0:
            if current_jma > self._prev_jma:
                self._trend = 1
            elif current_jma < self._prev_jma:
                self._trend = -1
            # 같으면 유지

        self._jma_val = current_jma
        self._prev_jma = current_jma
        self._count += 1

        return self._jma_val, self._trend

    def update(self, price):
        """확정 봉 — 상태 영구 갱신"""
        return self._step(price)

    def peek(self, price):
        """미확정 봉 — 상태 불변 미리보기"""
        snap = self._save_state()
        result = self._step(price)
        self._restore_state(snap)
        return result

    @property
    def value(self):
        return self._jma_val

    @property
    def trend(self):
        return self._trend

    @property
    def count(self):
        return self._count


def compute_jma(series, length=7, phase=50, power=2):
    """
    JMA 배치 계산 — VB.NET 원본 알고리즘

    alpha = beta^power 로 power가 직접 평활도를 결정:
      power=1 → 가장 민감 (빠른 추종)
      power=2 → 표준 (기본값)
      power=3 → 더 평탄 (노이즈 제거 강화)

    lookback 기간(index < length)에는 단순평균 사용
    """
    src = np.asarray(series, dtype=float)
    m = len(src)
    _length, pr, beta, alpha, _power = _jma_params(length, phase, power)

    jma_out = np.full(m, np.nan)

    e0 = np.nan
    e1 = 0.0
    e2 = 0.0
    last_jma = np.nan

    for i in range(m):
        price = src[i]

        # 초기화
        if np.isnan(e0):
            e0 = price
            e1 = 0.0
            e2 = 0.0
            last_jma = price

        # 3단계 필터
        e0 = (1.0 - alpha) * price + alpha * e0
        e1 = (price - e0) * (1.0 - beta) + beta * e1
        e2 = ((e0 + pr * e1 - last_jma)
              * (1.0 - alpha) ** 2
              + alpha ** 2 * e2)

        # lookback: 단순평균 / 이후: JMA
        if i < _length:
            current_jma = np.mean(src[:i + 1])
        else:
            current_jma = round(e2 + last_jma, 1)

        jma_out[i] = current_jma
        last_jma = current_jma

    return jma_out


def compute_jma_trend(df, length=7, phase=50, power=2):
    """JMA + 추세 판정 → df에 jma_line, jma_trend 추가"""
    jma = compute_jma(df["close"].values, length, phase, power)
    df["jma_line"] = jma
    n = len(df)
    trend = np.zeros(n)
    for i in range(1, n):
        if np.isnan(jma[i]) or np.isnan(jma[i - 1]):
            trend[i] = 0
        elif jma[i] > jma[i - 1]:
            trend[i] = 1
        elif jma[i] < jma[i - 1]:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]
    df["jma_trend"] = trend
    return df
# ═══════════════════════════════════════════════════════════════
#  틱강도 (Tick Intensity) — 분봉 동기화
# ═══════════════════════════════════════════════════════════════
def compute_tick_intensity(df_minute, df_tick, tick_size=30):
    """
    분봉 DataFrame의 각 봉 구간에서 완성된 틱캔들 수를 계산

    df_minute: 분봉 DataFrame (DatetimeIndex)
    df_tick:   틱캔들 DataFrame (DatetimeIndex) — tick_size 틱 단위
    tick_size: 틱캔들 크기 (참고용, 실제 카운트는 df_tick 행 수로)

    returns: df_minute에 tick_intensity, tick_ma5, tick_ma20 컬럼 추가
    """
    times = df_minute.index
    intensity = np.zeros(len(df_minute), dtype=int)

    for i in range(len(times)):
        if i == 0:
            # 첫 봉: 해당 봉 시간 이전 충분한 여유
            t_start = times[0] - pd.Timedelta(minutes=10)
        else:
            t_start = times[i-1]
        t_end = times[i]

        # 해당 구간의 틱캔들 수 카운트
        mask = (df_tick.index > t_start) & (df_tick.index <= t_end)
        intensity[i] = int(mask.sum())

    df_minute["tick_intensity"] = intensity

    # 5이평, 20이평
    ti = df_minute["tick_intensity"].values.astype(float)
    ma5 = np.full(len(ti), np.nan)
    ma20 = np.full(len(ti), np.nan)

    for i in range(4, len(ti)):
        ma5[i] = np.mean(ti[i-4:i+1])
    for i in range(19, len(ti)):
        ma20[i] = np.mean(ti[i-19:i+1])

    df_minute["tick_ma5"] = ma5
    df_minute["tick_ma20"] = ma20

    return df_minute


# ═══════════════════════════════════════════════════════════════
#  HTML 차트 생성 (lightweight-charts)
# ═══════════════════════════════════════════════════════════════
def build_html(df, code, name, tf_label, filter_name, filter_list,
               tf_options, current_tf, current_date="",
               tick_size=0):
    """lightweight-charts HTML — 문자열 결합 방식 (f-string 충돌 원천 차단)"""

    # numpy 타입 JSON 직렬화 지원
    class NpEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, (np.ndarray,)):
                return obj.tolist()
            return super().default(obj)

    # ── 1) 시간 컬럼 ──
    df = df.copy()
    if isinstance(df.index, pd.DatetimeIndex):
        if current_tf == "D":
            df["time"] = df.index.strftime("%Y-%m-%d")
        else:
            df["time"] = (df.index.astype(np.int64) // 10**9).astype(int)
    else:
        df["time"] = df.index.astype(str)

    # ── 2) 캔들 ──
    candles = []
    for _, r in df.iterrows():
        candles.append({"time": r["time"], "open": float(r["open"]),
                        "high": float(r["high"]), "low": float(r["low"]),
                        "close": float(r["close"])})

    # ── 3) 볼륨 ──
    volumes = []
    for _, r in df.iterrows():
        clr = "rgba(38,166,154,0.5)" if r["close"] >= r["open"] else "rgba(239,83,80,0.5)"
        volumes.append({"time": r["time"], "value": float(r["volume"]), "color": clr})

    # ── 4) ST 라인 ──
    st_data = []
    if "st_line" in df.columns:
        for _, r in df.iterrows():
            v = r["st_line"]
            if pd.notna(v):
                st_data.append({"time": r["time"], "value": float(v)})

    # ── 5) AEST 라인 ──
    aest_data = []
    if "aest_line" in df.columns:
        for _, r in df.iterrows():
            v = r["aest_line"]
            if pd.notna(v):
                clr = "#26a69a" if r.get("aest_trend", 0) == 1 else "#ef5350"
                aest_data.append({"time": r["time"], "value": float(v), "color": clr})

    # ── 5b) JMA 라인 ──
    jma_data = []
    if "jma_line" in df.columns:
        for _, r in df.iterrows():
            v = r["jma_line"]
            if pd.notna(v):
                clr = "#ffeb3b" if r.get("jma_trend", 0) == 1 else "#ff9800"
                jma_data.append({"time": r["time"], "value": float(v), "color": clr})

    # ── 6) 레인지 마커 ──
    range_marks = []
    if "aest_is_range" in df.columns:
        for _, r in df.iterrows():
            if r["aest_is_range"]:
                range_marks.append({"time": r["time"], "value": float(r["low"]),
                                    "color": "rgba(255,235,59,0.15)"})

    # ── 7) AEST 전환 마커 ──
    markers = []
    if "aest_trend" in df.columns:
        tv = df["aest_trend"].values
        for i in range(1, len(df)):
            if tv[i] != tv[i-1] and tv[i] != 0:
                row = df.iloc[i]
                if tv[i] == 1:
                    markers.append({"time": row["time"], "position": "belowBar",
                                    "color": "#26a69a", "shape": "arrowUp", "text": "UP"})
                else:
                    markers.append({"time": row["time"], "position": "aboveBar",
                                    "color": "#ef5350", "shape": "arrowDown", "text": "DN"})

    # ── 7b) JMA 전환 마커 ──
    jma_markers = []
    if "jma_trend" in df.columns:
        jt = df["jma_trend"].values
        for i in range(1, len(df)):
            if jt[i] != jt[i-1] and jt[i] != 0:
                row = df.iloc[i]
                if jt[i] == 1:
                    jma_markers.append({"time": row["time"], "position": "belowBar",
                                        "color": "#ffeb3b", "shape": "circle", "text": "J\u2191"})
                else:
                    jma_markers.append({"time": row["time"], "position": "aboveBar",
                                        "color": "#ff9800", "shape": "circle", "text": "J\u2193"})

    # ── 8) 통계 ──
    st_flips = 0
    if "st_trend" in df.columns:
        st_t = df["st_trend"].values
        for i in range(1, len(st_t)):
            if st_t[i] != st_t[i-1] and st_t[i] != 0:
                st_flips += 1
    aest_flips = 0
    if "aest_trend" in df.columns:
        at = df["aest_trend"].values
        for i in range(1, len(at)):
            if at[i] != at[i-1] and at[i] != 0:
                aest_flips += 1
    reduction = round((1 - aest_flips / max(st_flips, 1)) * 100, 1)
    range_bars = int(df["aest_is_range"].sum()) if "aest_is_range" in df.columns else 0
    range_pct = round(range_bars / max(len(df), 1) * 100, 1)

    last = df.iloc[-1]
    last_close = float(last["close"])
    last_aest = float(last["aest_line"]) if "aest_line" in df.columns and pd.notna(last.get("aest_line")) else 0
    last_trend_val = last.get("aest_trend", 0)
    last_trend_str = "\u25b2 \uc0c1\uc2b9" if last_trend_val == 1 else "\u25bc \ud558\ub77d"
    trend_clr = "#26a69a" if last_trend_val == 1 else "#ef5350"

    last_jma = float(last["jma_line"]) if "jma_line" in df.columns and pd.notna(last.get("jma_line")) else 0
    last_jma_trend = last.get("jma_trend", 0)
    jma_trend_str = "\u2191" if last_jma_trend == 1 else "\u2193"
    jma_clr = "#ffeb3b" if last_jma_trend == 1 else "#ff9800"

    # ── 틱강도 데이터 ──
    tick_int_data = []
    tick_ma5_data = []
    tick_ma20_data = []
    has_tick = "tick_intensity" in df.columns

    if has_tick:
        for _, r in df.iterrows():
            t = r["time"]
            ti_val = int(r["tick_intensity"])
            m5 = r.get("tick_ma5", np.nan)
            m20 = r.get("tick_ma20", np.nan)
            if pd.notna(m5) and pd.notna(m20):
                ti_clr = "rgba(38,166,154,0.7)" if m5 > m20 else "rgba(239,83,80,0.7)"
            else:
                ti_clr = "rgba(120,123,134,0.5)"
            tick_int_data.append({"time": t, "value": ti_val, "color": ti_clr})

            if pd.notna(m5):
                tick_ma5_data.append({"time": t, "value": float(m5)})
            if pd.notna(m20):
                tick_ma20_data.append({"time": t, "value": float(m20)})

    # ── 9) JSON ──
    candles_json = json.dumps(candles, ensure_ascii=False, cls=NpEncoder)
    volumes_json = json.dumps(volumes, ensure_ascii=False, cls=NpEncoder)
    st_json = json.dumps(st_data, ensure_ascii=False, cls=NpEncoder)
    aest_json = json.dumps(aest_data, ensure_ascii=False, cls=NpEncoder)
    markers_json = json.dumps(markers, ensure_ascii=False, cls=NpEncoder)
    jma_json = json.dumps(jma_data, ensure_ascii=False, cls=NpEncoder)
    jma_markers_json = json.dumps(jma_markers, ensure_ascii=False, cls=NpEncoder)
    tick_int_json = json.dumps(tick_int_data, ensure_ascii=False, cls=NpEncoder)
    tick_ma5_json = json.dumps(tick_ma5_data, ensure_ascii=False, cls=NpEncoder)
    tick_ma20_json = json.dumps(tick_ma20_data, ensure_ascii=False, cls=NpEncoder)

    # 마커 합치기 (AEST + JMA)
    all_markers = markers + jma_markers
    all_markers.sort(key=lambda m: str(m["time"]))
    all_markers_json = json.dumps(all_markers, ensure_ascii=False, cls=NpEncoder)

    # ── 10) 옵션 HTML ──
    tf_opts = ""
    for t in tf_options:
        sel = " selected" if t == current_tf else ""
        tf_opts += '<option value="' + t + '"' + sel + '>' + t + '</option>'

    filter_opts = ""
    for f in filter_list:
        sel = " selected" if f == filter_name else ""
        filter_opts += '<option value="' + f + '"' + sel + '>' + f + '</option>'

    tick_opts = ""
    for ts in [0, 15, 30, 60, 120]:
        lbl = "\uc5c6\uc74c" if ts == 0 else str(ts) + "\ud2f1"
        sel = " selected" if ts == tick_size else ""
        tick_opts += '<option value="' + str(ts) + '"' + sel + '>' + lbl + '</option>'

    date_val = current_date if current_date else ""
    date_dis = " disabled" if current_tf == "D" else ""

    # ── 디버그 ──
    print("  [HTML] candles=" + str(len(candles)) + " st=" + str(len(st_data))
          + " aest=" + str(len(aest_data)) + " jma=" + str(len(jma_data))
          + " markers=" + str(len(all_markers))
          + " tick_int=" + str(len(tick_int_data))
          + " date_ctrl='" + date_val + "' disabled=" + str(current_tf == "D"))

    # ═══════════════════════════════════════════════════════════
    #  HTML 조립 (문자열 결합)
    # ═══════════════════════════════════════════════════════════
    h = []
    h.append('<!DOCTYPE html>')
    h.append('<html lang="ko">')
    h.append('<head>')
    h.append('<meta charset="UTF-8">')
    h.append('<title>AEST \u2014 ' + code + ' ' + name + ' [' + tf_label + ']</title>')
    h.append('''<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#131722; color:#d1d4dc; font-family:'Segoe UI',sans-serif; }
#toolbar {
  display:flex; align-items:center; gap:8px;
  padding:8px 16px; background:#1e222d; border-bottom:1px solid #2a2e39;
  flex-wrap:wrap;
}
#toolbar label { color:#787b86; font-size:12px; margin-left:6px; }
#toolbar input[type="text"] {
  width:90px; padding:4px 8px; background:#2a2e39; border:1px solid #363a45;
  color:#d1d4dc; border-radius:4px; font-size:13px;
}
#toolbar input[type="date"] {
  padding:4px 8px; background:#2a2e39; border:1px solid #363a45;
  color:#d1d4dc; border-radius:4px; font-size:13px; min-width:140px;
}
#toolbar input[type="date"]:disabled { opacity:0.4; cursor:not-allowed; }
#toolbar select {
  padding:4px 8px; background:#2a2e39; border:1px solid #363a45;
  color:#d1d4dc; border-radius:4px; font-size:13px;
}
#toolbar button {
  padding:5px 16px; background:#2962ff; color:#fff; border:none;
  border-radius:4px; cursor:pointer; font-size:13px; font-weight:bold;
}
#toolbar button:hover { background:#1e53e5; }
.sep { width:1px; height:24px; background:#363a45; margin:0 4px; }
#info {
  display:flex; align-items:center; gap:16px;
  padding:6px 16px; background:#1e222d; border-bottom:1px solid #2a2e39;
  font-size:12px; flex-wrap:wrap;
}
.stat { color:#787b86; }
.stat b { color:#d1d4dc; }
.trend-badge { padding:2px 8px; border-radius:3px; font-weight:bold; font-size:12px; }
#chart { width:100%; height:calc(100vh - 90px); }
#error { color:#ef5350; padding:20px; font-size:16px; display:none; }
</style>''')
    h.append('</head>')
    h.append('<body>')

    # ── TOOLBAR ──
    h.append('<div id="toolbar">')
    h.append('  <label>\uc885\ubaa9</label>')
    h.append('  <input type="text" id="codeInput" value="' + code + '" placeholder="005930" onkeydown="if(event.key===\'Enter\')goChart()">')
    h.append('  <label>\ud0c0\uc784\ud504\ub808\uc784</label>')
    h.append('  <select id="tfSelect" onchange="onTfChange()">' + tf_opts + '</select>')
    h.append('  <label>\uc77c\uc790</label>')
    h.append('  <input type="date" id="dateInput" value="' + date_val + '"' + date_dis + '>')
    h.append('  <div class="sep"></div>')
    h.append('  <label>\ud6a1\ubcf4\ud544\ud130</label>')
    h.append('  <select id="filterSelect">' + filter_opts + '</select>')
    h.append('  <div class="sep"></div>')
    h.append('  <label>\ud2f1\uac15\ub3c4</label>')
    h.append('  <select id="tickSelect">' + tick_opts + '</select>')
    h.append('  <div class="sep"></div>')
    h.append('  <button onclick="goChart()">\uc801\uc6a9</button>')
    h.append('</div>')

    # ── INFO BAR ──
    h.append('<div id="info">')
    h.append('  <span class="stat"><b>' + code + ' ' + name + '</b> &nbsp; ' + tf_label + '</span>')
    h.append('  <span class="stat">\uc885\uac00 <b>' + format(last_close, ',.0f') + '</b></span>')
    h.append('  <span class="stat">AEST <b>' + format(last_aest, ',.0f') + '</b></span>')
    h.append('  <span class="trend-badge" style="background:' + trend_clr + ';color:#fff">' + last_trend_str + '</span>')
    h.append('  <span class="stat">JMA <b style="color:' + jma_clr + '">' + format(last_jma, ',.0f') + ' ' + jma_trend_str + '</b></span>')
    h.append('  <span class="stat">ST\uc804\ud658 <b>' + str(st_flips) + '\ud68c</b></span>')
    h.append('  <span class="stat">AEST\uc804\ud658 <b>' + str(aest_flips) + '\ud68c</b></span>')
    h.append('  <span class="stat">\uac10\uc18c <b>' + str(reduction) + '%</b></span>')
    h.append('  <span class="stat">\ud6a1\ubcf4 <b>' + str(range_bars) + '\ubcf4 (' + str(range_pct) + '%)</b></span>')
    h.append('  <span class="stat">\ucd1d <b>' + str(len(df)) + '\ubcf4</b></span>')
    h.append('  <span class="stat">\ud544\ud130 <b>' + filter_name + '</b></span>')
    if has_tick:
        last_ti = int(last.get("tick_intensity", 0))
        h.append('  <span class="stat">\ud2f1\uac15\ub3c4 <b>' + str(last_ti) + '</b> (' + str(tick_size) + '\ud2f1)</span>')
    h.append('</div>')

    # ── CHART + ERROR ──
    h.append('<div id="chart"></div>')
    h.append('<div id="error"></div>')

    # ── JAVASCRIPT ──
    h.append('<script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>')
    h.append('<script>')

    h.append('''
function onTfChange() {
  var tf = document.getElementById('tfSelect').value;
  var dateEl = document.getElementById('dateInput');
  if (tf === 'D') {
    dateEl.disabled = true;
    dateEl.value = '';
  } else {
    dateEl.disabled = false;
  }
}

function goChart() {
  var code = document.getElementById('codeInput').value.trim();
  var tf = document.getElementById('tfSelect').value;
  var filter = document.getElementById('filterSelect').value;
  var date = document.getElementById('dateInput').value || '';
  var tick = document.getElementById('tickSelect').value;
  if (!code) { alert('종목코드를 입력하세요'); return; }
  var url = '/?code=' + code + '&tf=' + tf + '&filter=' + encodeURIComponent(filter);
  if (date && tf !== 'D') { url += '&date=' + date; }
  if (tick && tick !== '0') { url += '&tick=' + tick; }
  window.location.href = url;
}
''')

    # ── 차트 생성 ──
    h.append('try {')
    h.append('  var container = document.getElementById("chart");')
    h.append('  var chart = LightweightCharts.createChart(container, {')
    h.append('    width: container.clientWidth, height: container.clientHeight,')
    h.append('    layout: { background: { type: "solid", color: "#131722" }, textColor: "#d1d4dc" },')
    h.append('    grid: { vertLines: { color: "#1e222d" }, horzLines: { color: "#1e222d" } },')
    h.append('    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },')
    h.append('    rightPriceScale: { borderColor: "#2a2e39" },')
    h.append('    timeScale: { borderColor: "#2a2e39", timeVisible: true, secondsVisible: false }')
    h.append('  });')

    # 캔들
    h.append('  var cs = chart.addCandlestickSeries({')
    h.append('    upColor:"#26a69a", downColor:"#ef5350",')
    h.append('    borderUpColor:"#26a69a", borderDownColor:"#ef5350",')
    h.append('    wickUpColor:"#26a69a", wickDownColor:"#ef5350"')
    h.append('  });')
    h.append('  cs.setData(' + candles_json + ');')

    # 볼륨
    h.append('  var vs = chart.addHistogramSeries({')
    h.append('    priceFormat:{type:"volume"}, priceScaleId:"vol"')
    h.append('  });')
    h.append('  chart.priceScale("vol").applyOptions({scaleMargins:{top:0.85,bottom:0}});')
    h.append('  vs.setData(' + volumes_json + ');')

    # ST
    if len(st_data) > 0:
        h.append('  var stS = chart.addLineSeries({')
        h.append('    color:"#787b86", lineWidth:1, lineStyle:2,')
        h.append('    lastValueVisible:false, priceLineVisible:false, title:"ST"')
        h.append('  });')
        h.append('  stS.setData(' + st_json + ');')

    # AEST
    if len(aest_data) > 0:
        h.append('  var aS = chart.addLineSeries({')
        h.append('    lineWidth:3, lastValueVisible:true,')
        h.append('    priceLineVisible:false, title:"AEST"')
        h.append('  });')
        h.append('  aS.setData(' + aest_json + ');')

    # JMA
    if len(jma_data) > 0:
        h.append('  var jmaS = chart.addLineSeries({')
        h.append('    lineWidth:2, lastValueVisible:true,')
        h.append('    priceLineVisible:false, title:"JMA"')
        h.append('  });')
        h.append('  jmaS.setData(' + jma_json + ');')

    # 마커 (AEST + JMA 통합)
    if len(all_markers) > 0:
        h.append('  cs.setMarkers(' + all_markers_json + ');')

    # ── 틱강도 패널 ──
    if has_tick and len(tick_int_data) > 0:
        h.append('  // 틱강도 히스토그램')
        h.append('  var tiS = chart.addHistogramSeries({')
        h.append('    priceFormat:{type:"volume"}, priceScaleId:"tick_int"')
        h.append('  });')
        h.append('  chart.priceScale("tick_int").applyOptions({scaleMargins:{top:0.75,bottom:0}});')
        h.append('  tiS.setData(' + tick_int_json + ');')

        # 5이평
        if len(tick_ma5_data) > 0:
            h.append('  var tm5 = chart.addLineSeries({')
            h.append('    color:"#ffeb3b", lineWidth:1, priceScaleId:"tick_int",')
            h.append('    lastValueVisible:false, priceLineVisible:false, title:"TI5"')
            h.append('  });')
            h.append('  tm5.setData(' + tick_ma5_json + ');')

        # 20이평
        if len(tick_ma20_data) > 0:
            h.append('  var tm20 = chart.addLineSeries({')
            h.append('    color:"#2962ff", lineWidth:1, priceScaleId:"tick_int",')
            h.append('    lastValueVisible:false, priceLineVisible:false, title:"TI20"')
            h.append('  });')
            h.append('  tm20.setData(' + tick_ma20_json + ');')

    h.append('  chart.timeScale().fitContent();')
    h.append('  window.addEventListener("resize", function(){')
    h.append('    chart.applyOptions({width:container.clientWidth,height:container.clientHeight});')
    h.append('  });')

    h.append('} catch(e) {')
    h.append('  var ed = document.getElementById("error");')
    h.append('  ed.style.display="block";')
    h.append('  ed.innerText="Chart Error: "+e.message;')
    h.append('  console.error(e);')
    h.append('}')

    h.append('</script>')
    h.append('</body>')
    h.append('</html>')

    return '\n'.join(h)
