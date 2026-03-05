#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AEST (Adaptive Equity SuperTrend) — Lightweight Chart Viewer
=============================================================
Server : server32 (github.com/hoonoh57/server32)
API doc: http://localhost:8082/help
"""

import argparse
import json
import http.server
import os
import threading
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests


# ═══════════════════════════════════════════════════════════════
#  1. 설정
# ═══════════════════════════════════════════════════════════════
@dataclass
class AESTConfig:
    # ATR / SuperTrend
    atr_len: int = 14
    base_mult: float = 3.0

    # Efficiency Ratio
    er_len: int = 20
    er_sensitivity: float = 0.5
    er_min_mult: float = 2.0
    er_max_mult: float = 5.0

    # Asymmetric band
    use_asymmetric: bool = True

    # Equity feedback
    eq_ma_len: int = 40
    eq_freeze_dd: float = 25.0   # % drawdown → FROZEN
    eq_strict_mult: float = 2.0

    # Thaw (FROZEN 해제)
    thaw_mode: str = "price"     # price / time / both
    thaw_price_mult: float = 1.5
    thaw_min_bars: int = 60
    thaw_max_bars: int = 250

    # Virtual trading
    capital: float = 10_000_000
    position_pct: float = 0.95
    commission: float = 0.00015
    tax: float = 0.0018
    slippage: float = 0.001


# ═══════════════════════════════════════════════════════════════
#  2. 서버 클라이언트  (server32 매뉴얼 준수)
# ═══════════════════════════════════════════════════════════════
class ServerClient:
    """
    server32 REST API 클라이언트
    ──────────────────────────────
    응답 envelope: { "Success": bool, "Message": str, "Data": ... }
    """

    def __init__(self, host: str = "localhost", port: int = 8082):
        self.base = f"http://{host}:{port}"

    # ── 공통 GET ──
    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{self.base}{path}"
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        js = r.json()
        if not js.get("Success", False):
            raise RuntimeError(f"API Error: {js.get('Message', 'unknown')}")
        return js["Data"]

    # ── [16] GET /api/market/symbol?code={code} ──
    def symbol_name(self, code: str) -> str:
        """종목명 조회"""
        try:
            data = self._get("/api/market/symbol", {"code": code})
            return data.get("name", code)
        except Exception:
            return code

    # ── [13] GET /api/market/candles/daily?code=&date=&stopDate= ──
    def daily_candles(self, code: str, years: int = 5) -> pd.DataFrame:
        """
        일봉 데이터 다운로드
        date     = 최근 날짜 (yyyyMMdd)
        stopDate = 과거 시작 날짜 (yyyyMMdd)
        """
        now = datetime.now()
        date_str = now.strftime("%Y%m%d")
        stop_str = (now - timedelta(days=365 * years)).strftime("%Y%m%d")

        print(f"  API: /api/market/candles/daily?code={code}&date={date_str}&stopDate={stop_str}")
        data = self._get("/api/market/candles/daily", {
            "code": code,
            "date": date_str,
            "stopDate": stop_str,
        })

        if not data:
            raise RuntimeError("일봉 데이터가 비어 있습니다")

        rows = []
        for d in data:
            # 매뉴얼: 일자, 시가, 고가, 저가, 현재가, 거래량
            dt = pd.to_datetime(str(d["일자"]))
            rows.append({
                "date":   dt,
                "open":   abs(int(d["시가"])),
                "high":   abs(int(d["고가"])),
                "low":    abs(int(d["저가"])),
                "close":  abs(int(d.get("현재가", d.get("종가", 0)))),
                "volume": abs(int(d["거래량"])),
            })

        df = pd.DataFrame(rows)
        df.sort_values("date", inplace=True)
        df.set_index("date", inplace=True)
        df = df[df["volume"] > 0]
        print(f"  {len(df)}봉 로드 ({df.index[0]} ~ {df.index[-1]})")
        return df

    # ── [14] GET /api/market/candles/minute?code=&tick=&stopTime= ──
    def minute_candles(self, code: str, tick: int = 1) -> pd.DataFrame:
        """
        분봉 데이터 다운로드
        tick     = 분 단위 (1, 3, 5 ...)
        stopTime = 과거 시작 시간 (yyyyMMddHHmmss)
        """
        stop_str = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d") + "090000"

        print(f"  API: /api/market/candles/minute?code={code}&tick={tick}&stopTime={stop_str}")
        data = self._get("/api/market/candles/minute", {
            "code": code,
            "tick": tick,
            "stopTime": stop_str,
        })

        if not data:
            raise RuntimeError("분봉 데이터가 비어 있습니다")

        rows = []
        for d in data:
            # 매뉴얼: 체결시간, 시가, 고가, 저가, 현재가, 거래량
            ts = str(d["체결시간"])
            dt = pd.to_datetime(ts)
            rows.append({
                "date":   dt,
                "open":   abs(int(d["시가"])),
                "high":   abs(int(d["고가"])),
                "low":    abs(int(d["저가"])),
                "close":  abs(int(d["현재가"])),
                "volume": abs(int(d["거래량"])),
            })

        df = pd.DataFrame(rows)
        df.sort_values("date", inplace=True)
        df.set_index("date", inplace=True)
        df = df[df["volume"] > 0]
        print(f"  {len(df)}봉 로드 ({df.index[0]} ~ {df.index[-1]})")
        return df


# ═══════════════════════════════════════════════════════════════
#  3. Standard SuperTrend
# ═══════════════════════════════════════════════════════════════
def compute_supertrend(df: pd.DataFrame, atr_len: int = 14, mult: float = 3.0):
    """표준 SuperTrend — st_line, st_trend 컬럼 추가"""
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(df)

    # True Range → ATR (SMA)
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    tr[0] = h[0] - l[0]

    atr = np.zeros(n)
    atr[:atr_len] = np.nan
    atr[atr_len - 1] = np.mean(tr[:atr_len])
    for i in range(atr_len, n):
        atr[i] = (atr[i - 1] * (atr_len - 1) + tr[i]) / atr_len

    mid = (h + l) / 2.0
    upper = mid + mult * atr
    lower = mid - mult * atr

    trend = np.ones(n)
    st_line = np.full(n, np.nan)

    for i in range(1, n):
        if np.isnan(atr[i]):
            continue

        # Lock bands
        if lower[i] < lower[i - 1] and c[i - 1] > lower[i - 1]:
            lower[i] = lower[i - 1]
        if upper[i] > upper[i - 1] and c[i - 1] < upper[i - 1]:
            upper[i] = upper[i - 1]

        # Trend
        if trend[i - 1] == 1:
            trend[i] = -1 if c[i] < lower[i] else 1
        else:
            trend[i] = 1 if c[i] > upper[i] else -1

        st_line[i] = lower[i] if trend[i] == 1 else upper[i]

    df["st_line"] = st_line
    df["st_trend"] = trend
    return df


# ═══════════════════════════════════════════════════════════════
#  4. AEST (Adaptive Equity SuperTrend)
# ═══════════════════════════════════════════════════════════════
def compute_aest(df: pd.DataFrame, cfg: AESTConfig) -> pd.DataFrame:
    """
    AEST 지표 계산
    출력 컬럼: aest_line, aest_trend, aest_state, aest_mult
    """
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(df)

    # ── 4-1. EATR (EMA of True Range) ──
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    tr[0] = h[0] - l[0]

    eatr = np.zeros(n)
    alpha = 2.0 / (cfg.atr_len + 1)
    eatr[0] = tr[0]
    for i in range(1, n):
        eatr[i] = alpha * tr[i] + (1 - alpha) * eatr[i - 1]

    # ── 4-2. Efficiency Ratio ──
    er = np.zeros(n)
    for i in range(cfg.er_len, n):
        direction = abs(c[i] - c[i - cfg.er_len])
        volatility = sum(abs(c[j] - c[j - 1]) for j in range(i - cfg.er_len + 1, i + 1))
        er[i] = direction / volatility if volatility > 0 else 0

    er_mult = np.full(n, cfg.base_mult)
    for i in range(cfg.er_len, n):
        raw = cfg.er_min_mult + (cfg.er_max_mult - cfg.er_min_mult) * (1 - er[i] ** cfg.er_sensitivity)
        er_mult[i] = np.clip(raw, cfg.er_min_mult, cfg.er_max_mult)

    # ── 4-3. 밴드 계산 ──
    mid = (h + l) / 2.0
    upper = mid + er_mult * eatr
    lower = mid - er_mult * eatr

    # ── 4-4. 메인 루프: 추세 + 가상매매 + 상태 ──
    trend = np.ones(n)
    aest_line = np.full(n, np.nan)
    final_mult = np.full(n, cfg.base_mult)
    state = ["NORMAL"] * n

    # 가상 자본
    equity = cfg.capital
    position = 0        # 보유 수량
    avg_price = 0.0
    eq_peak = equity
    frozen_bar = 0
    frozen_high = 0.0
    current_state = "NORMAL"

    for i in range(1, n):
        if np.isnan(eatr[i]):
            continue

        # ── 상태에 따른 승수 조정 ──
        if current_state == "FROZEN":
            m = er_mult[i] * cfg.eq_strict_mult * 2
        elif current_state == "STRICT":
            m = er_mult[i] * cfg.eq_strict_mult
        else:
            m = er_mult[i]

        final_mult[i] = m

        # 밴드 재계산
        ub = mid[i] + m * eatr[i]
        lb = mid[i] - m * eatr[i]

        # 비대칭 밴드
        if cfg.use_asymmetric:
            if trend[i - 1] == 1:
                ub = mid[i] + m * 1.2 * eatr[i]
                lb = mid[i] - m * 0.8 * eatr[i]
            else:
                ub = mid[i] + m * 0.8 * eatr[i]
                lb = mid[i] - m * 1.2 * eatr[i]

        # Lock bands
        if not np.isnan(lower[i - 1]):
            if lb < lower[i - 1] and c[i - 1] > lower[i - 1]:
                lb = lower[i - 1]
        if not np.isnan(upper[i - 1]):
            if ub > upper[i - 1] and c[i - 1] < upper[i - 1]:
                ub = upper[i - 1]

        upper[i] = ub
        lower[i] = lb

        # ── 추세 결정 ──
        if current_state == "FROZEN":
            # FROZEN: 추세 전환 차단
            candidate = -1 if c[i] < lb else (1 if c[i] > ub else trend[i - 1])

            # Thaw 조건 확인
            frozen_bar += 1
            frozen_high = max(frozen_high, h[i])
            thaw = False

            if cfg.thaw_mode == "price":
                if frozen_bar >= cfg.thaw_min_bars:
                    if c[i] > frozen_high * cfg.thaw_price_mult:
                        thaw = True
            elif cfg.thaw_mode == "time":
                if frozen_bar >= cfg.thaw_max_bars:
                    thaw = True
            elif cfg.thaw_mode == "both":
                if frozen_bar >= cfg.thaw_min_bars and c[i] > frozen_high * cfg.thaw_price_mult:
                    thaw = True
                elif frozen_bar >= cfg.thaw_max_bars:
                    thaw = True

            if thaw:
                current_state = "STRICT"
                eq_peak = equity
                trend[i] = candidate
            else:
                trend[i] = trend[i - 1]  # 추세 전환 차단
        else:
            # NORMAL / STRICT: 일반 추세 결정
            if trend[i - 1] == 1:
                trend[i] = -1 if c[i] < lb else 1
            else:
                trend[i] = 1 if c[i] > ub else -1

        aest_line[i] = lb if trend[i] == 1 else ub

        # ── 가상 매매 (추세 전환 시) ──
        if i > 1 and trend[i] != trend[i - 1] and current_state != "FROZEN":
            price = c[i]

            if trend[i] == 1 and position == 0:
                # BUY
                cost = price * (1 + cfg.slippage + cfg.commission)
                qty = int((equity * cfg.position_pct) / cost)
                if qty > 0:
                    position = qty
                    avg_price = cost
                    equity -= qty * cost

            elif trend[i] == -1 and position > 0:
                # SELL
                proceeds = price * (1 - cfg.slippage - cfg.commission - cfg.tax)
                equity += position * proceeds
                position = 0
                avg_price = 0.0

        # 평가 자산
        eval_equity = equity + position * c[i]
        eq_peak = max(eq_peak, eval_equity)

        # DD 계산
        dd = (eq_peak - eval_equity) / eq_peak * 100 if eq_peak > 0 else 0

        # 상태 전이
        if current_state == "NORMAL":
            if dd >= cfg.eq_freeze_dd:
                current_state = "FROZEN"
                frozen_bar = 0
                frozen_high = h[i]
            elif dd >= cfg.eq_freeze_dd * 0.5:
                current_state = "STRICT"
        elif current_state == "STRICT":
            if dd >= cfg.eq_freeze_dd:
                current_state = "FROZEN"
                frozen_bar = 0
                frozen_high = h[i]
            elif dd < cfg.eq_freeze_dd * 0.3:
                current_state = "NORMAL"
        # FROZEN → 해제는 위 thaw 로직에서 처리

        state[i] = current_state

    df["aest_line"] = aest_line
    df["aest_trend"] = trend
    df["aest_state"] = state
    df["aest_mult"] = final_mult
    return df


# ═══════════════════════════════════════════════════════════════
#  5. HTML 차트 생성 (lightweight-charts 4.x)
# ═══════════════════════════════════════════════════════════════
def build_html(df: pd.DataFrame, code: str, name: str, tf_label: str, cfg: AESTConfig) -> str:
    """lightweight-charts HTML — AEST 단일 선 (구간별 색상)"""

    df = df.copy()

    # ── time 컬럼 생성 ──
    if isinstance(df.index, pd.DatetimeIndex):
        idx = df.index
    else:
        idx = pd.to_datetime(df.index)

    if tf_label == "일봉":
        df["time"] = idx.strftime("%Y-%m-%d")
    else:
        # 분봉: UNIX timestamp (초 단위)
        df["time"] = (idx.astype("int64") // 10**9).astype(int)

    # ── 캔들 ──
    candles = []
    volumes = []
    for _, r in df.iterrows():
        t = r["time"]
        # 분봉이면 int, 일봉이면 str
        if isinstance(t, (np.integer,)):
            t = int(t)
        candles.append({
            "time": t,
            "open":  float(r["open"]),
            "high":  float(r["high"]),
            "low":   float(r["low"]),
            "close": float(r["close"]),
        })
        vc = "#26a69a80" if r["close"] >= r["open"] else "#ef535080"
        volumes.append({"time": t, "value": int(r["volume"]), "color": vc})

    # ── Standard ST ──
    st_data = []
    for _, r in df.iterrows():
        v = r.get("st_line")
        if pd.notna(v):
            t = int(r["time"]) if isinstance(r["time"], (np.integer,)) else r["time"]
            st_data.append({"time": t, "value": round(float(v), 2)})

    # ── AEST: 단일 선, 포인트별 색상 ──
    aest_data = []
    for _, r in df.iterrows():
        v = r.get("aest_line")
        if pd.notna(v):
            t = int(r["time"]) if isinstance(r["time"], (np.integer,)) else r["time"]
            color = "#26a69a" if r["aest_trend"] == 1 else "#ef5350"
            aest_data.append({
                "time":  t,
                "value": round(float(v), 2),
                "color": color,
            })

    # ── 마커 ──
    markers = []
    trends = df["aest_trend"].values
    times = df["time"].values
    for i in range(1, len(df)):
        if pd.isna(trends[i]) or pd.isna(trends[i - 1]):
            continue
        t = int(times[i]) if isinstance(times[i], (np.integer,)) else times[i]
        if trends[i] == 1 and trends[i - 1] == -1:
            markers.append({
                "time": t, "position": "belowBar",
                "color": "#26a69a", "shape": "arrowUp", "text": "UP",
            })
        elif trends[i] == -1 and trends[i - 1] == 1:
            markers.append({
                "time": t, "position": "aboveBar",
                "color": "#ef5350", "shape": "arrowDown", "text": "DN",
            })

    # ── 통계 ──
    st_flips = 0
    if "st_trend" in df.columns:
        sa = df["st_trend"].dropna().values
        st_flips = sum(1 for i in range(1, len(sa)) if sa[i] != sa[i - 1])

    aa = df["aest_trend"].dropna().values
    aest_flips = sum(1 for i in range(1, len(aa)) if aa[i] != aa[i - 1])
    reduction = round((1 - aest_flips / max(st_flips, 1)) * 100)

    # ── 헤더 ──
    last = df.iloc[-1]
    trend_str = "▲ 상승" if last["aest_trend"] == 1 else "▼ 하락"
    trend_color = "#26a69a" if last["aest_trend"] == 1 else "#ef5350"
    state_val = last.get("aest_state", "NORMAL")
    mult_val = last.get("aest_mult", cfg.base_mult)
    title = f"AEST Indicator — {code} {name} [{tf_label}]"

    # ── JSON ──
    candles_json = json.dumps(candles, ensure_ascii=False)
    volumes_json = json.dumps(volumes, ensure_ascii=False)
    st_json = json.dumps(st_data, ensure_ascii=False)
    aest_json = json.dumps(aest_data, ensure_ascii=False)
    markers_json = json.dumps(markers, ensure_ascii=False)

    # ── 디버그 ──
    print(f"  [DEBUG] candle[0]: {candles[0] if candles else 'empty'}")
    print(f"  [DEBUG] aest[0]:   {aest_data[0] if aest_data else 'empty'}")
    print(f"  [DEBUG] candles: {len(candles)}개, st: {len(st_data)}개, aest: {len(aest_data)}개")

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ margin:0; background:#131722; color:#d1d4dc; font-family:'Consolas','Courier New',monospace; }}
  #title {{ padding:8px 16px; font-size:16px; font-weight:bold; }}
  #info {{ padding:2px 16px 8px; font-size:13px; color:#aaa; }}
  #chart {{ width:100%; height:calc(100vh - 60px); }}
  #error {{ color:#ef5350; padding:16px; display:none; font-size:14px; }}
</style>
</head><body>
<div id="title">{title}</div>
<div id="info">
  종가: {last['close']:,.0f} &nbsp;&nbsp;
  AEST: <span style="color:{trend_color}">{last['aest_line']:,.0f}</span> &nbsp;&nbsp;
  추세: <span style="color:{trend_color}">{trend_str}</span> &nbsp;&nbsp;
  상태: {state_val} &nbsp;&nbsp;
  승수: {mult_val:.2f} &nbsp;&nbsp;
  ST전환: {st_flips}회 &nbsp;&nbsp;
  AEST전환: {aest_flips}회 ({reduction}% 감소) &nbsp;&nbsp;
  {len(df)}봉
</div>
<div id="error"></div>
<div id="chart"></div>

<script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
<script>
try {{
    if (typeof LightweightCharts === 'undefined') {{
        throw new Error('lightweight-charts 라이브러리를 로드할 수 없습니다');
    }}

    const chartEl = document.getElementById('chart');
    const chart = LightweightCharts.createChart(chartEl, {{
        width:  chartEl.clientWidth,
        height: chartEl.clientHeight || 700,
        layout: {{ background: {{ color: '#131722' }}, textColor: '#d1d4dc' }},
        grid:   {{ vertLines: {{ color: '#1e222d' }}, horzLines: {{ color: '#1e222d' }} }},
        crosshair: {{ mode: 0 }},
        rightPriceScale: {{ borderColor: '#2a2e39' }},
        timeScale: {{ borderColor: '#2a2e39', timeVisible: true, secondsVisible: false }},
    }});

    /* 캔들 */
    const cs = chart.addCandlestickSeries({{
        upColor: '#26a69a', downColor: '#ef5350',
        borderUpColor: '#26a69a', borderDownColor: '#ef5350',
        wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    }});
    cs.setData({candles_json});

    /* 거래량 */
    const vs = chart.addHistogramSeries({{
        priceFormat: {{ type: 'volume' }},
        priceScaleId: 'volume',
    }});
    chart.priceScale('volume').applyOptions({{
        scaleMargins: {{ top: 0.85, bottom: 0 }},
    }});
    vs.setData({volumes_json});

    /* Standard ST (회색 점선) */
    const stS = chart.addLineSeries({{
        color: '#888888', lineWidth: 1, lineStyle: 2,
        title: 'ST', lastValueVisible: true, priceLineVisible: false,
    }});
    stS.setData({st_json});

    /* AEST (단일 선, 포인트별 색상) */
    const aestS = chart.addLineSeries({{
        lineWidth: 3,
        lastValueVisible: true,
        priceLineVisible: false,
        title: 'AEST',
    }});
    aestS.setData({aest_json});

    /* 마커 */
    aestS.setMarkers({markers_json});

    chart.timeScale().fitContent();

    /* 리사이즈 */
    window.addEventListener('resize', () => {{
        chart.applyOptions({{
            width:  chartEl.clientWidth,
            height: chartEl.clientHeight,
        }});
    }});

}} catch(e) {{
    const el = document.getElementById('error');
    el.style.display = 'block';
    el.textContent = 'ERROR: ' + e.message;
    console.error(e);
}}
</script>
</body></html>"""

    return html


# ═══════════════════════════════════════════════════════════════
#  6. 요약 출력
# ═══════════════════════════════════════════════════════════════
def print_summary(df: pd.DataFrame, code: str, name: str, cfg: AESTConfig):
    st_flips = 0
    if "st_trend" in df.columns:
        sa = df["st_trend"].dropna().values
        st_flips = sum(1 for i in range(1, len(sa)) if sa[i] != sa[i - 1])

    aa = df["aest_trend"].dropna().values
    aest_flips = sum(1 for i in range(1, len(aa)) if aa[i] != aa[i - 1])
    reduction = round((1 - aest_flips / max(st_flips, 1)) * 100)

    last = df.iloc[-1]
    trend_str = "▲ 상승" if last["aest_trend"] == 1 else "▼ 하락"
    state_val = last.get("aest_state", "NORMAL")
    mult_val = last.get("aest_mult", cfg.base_mult)

    # 상태 분포
    states = df["aest_state"].value_counts()

    print()
    print(f"  ST 전환: {st_flips}회")
    print(f"  AEST 전환: {aest_flips}회 ({reduction}% 감소)")
    print()
    print(f"  현재: {last['close']:,.0f}  AEST: {last['aest_line']:,.0f}  {trend_str}  {state_val}")
    print(f"  승수: {mult_val:.2f}")
    print()
    print(f"  상태 분포:")
    for s in ["NORMAL", "STRICT", "FROZEN"]:
        cnt = states.get(s, 0)
        pct = cnt / len(df) * 100
        print(f"    {s:8s}: {cnt:5d}봉 ({pct:.1f}%)")


# ═══════════════════════════════════════════════════════════════
#  7. 메인
# ═══════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="AEST Lightweight Chart Viewer")
    parser.add_argument("code", help="종목코드 (예: 005930)")
    parser.add_argument("--tf", type=int, default=0,
                        help="타임프레임: 0=일봉(기본), 1/3/5/...=분봉")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument("--chart_port", type=int, default=9090, help="차트 HTTP 서버 포트")

    # AEST 파라미터
    parser.add_argument("--base_mult", type=float, default=3.0)
    parser.add_argument("--atr_len", type=int, default=14)
    parser.add_argument("--eq_freeze", type=float, default=25.0)
    parser.add_argument("--eq_strict", type=float, default=2.0)
    parser.add_argument("--thaw_mode", default="price", choices=["price", "time", "both"])
    parser.add_argument("--thaw_price_mult", type=float, default=1.5)
    parser.add_argument("--thaw_min_bars", type=int, default=60)
    parser.add_argument("--thaw_max_bars", type=int, default=250)
    parser.add_argument("--no_asymmetric", action="store_true")

    args = parser.parse_args()

    print("=" * 60)
    print("  AEST Lightweight Chart Viewer")
    print("=" * 60)

    # ── 설정 ──
    cfg = AESTConfig(
        atr_len=args.atr_len,
        base_mult=args.base_mult,
        eq_freeze_dd=args.eq_freeze,
        eq_strict_mult=args.eq_strict,
        use_asymmetric=not args.no_asymmetric,
        thaw_mode=args.thaw_mode,
        thaw_price_mult=args.thaw_price_mult,
        thaw_min_bars=args.thaw_min_bars,
        thaw_max_bars=args.thaw_max_bars,
    )

    # ── 데이터 로드 ──
    client = ServerClient(args.host, args.port)

    print(f"\n  종목: {args.code}", end=" ")
    nm = client.symbol_name(args.code)
    print(nm)

    if args.tf == 0:
        tf_label = "일봉"
        print(f"  타임프레임: {tf_label}")
        df = client.daily_candles(args.code)
    else:
        tf_label = f"{args.tf}분봉"
        print(f"  타임프레임: {tf_label}")
        df = client.minute_candles(args.code, tick=args.tf)

    # ── 지표 계산 ──
    print("  Standard SuperTrend 계산...")
    df = compute_supertrend(df, cfg.atr_len, cfg.base_mult)

    print("  AEST 계산...")
    df = compute_aest(df, cfg)

    # ── 요약 ──
    print_summary(df, args.code, nm, cfg)

    # ── HTML 생성 ──
    print("\n  차트 생성...")
    html = build_html(df, args.code, nm, tf_label, cfg)

    out_path = os.path.join(os.getcwd(), "aest_chart.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  저장: {out_path}")

    # ── HTTP 서버 ──
    os.chdir(os.path.dirname(out_path))

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *a):
            pass

    server = http.server.HTTPServer(("0.0.0.0", args.chart_port), QuietHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    url = f"http://localhost:{args.chart_port}/aest_chart.html"
    print(f"  서버: {url}")
    webbrowser.open(url)

    print(f"\n  Ctrl+C 로 종료")
    try:
        t.join()
    except KeyboardInterrupt:
        print("\n  종료!")
        server.shutdown()


if __name__ == "__main__":
    main()
