#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aest_app.py — AEST 차트 뷰어
  차트에서 종목코드, 타임프레임, 일자, 횡보필터, 틱강도 변경 가능

  python aest_app.py
  python aest_app.py 005930
  python aest_app.py 034020 --tf m5 --filter LonesomeTheBlue
  python aest_app.py 005930 --tf m3 --date 2026-03-05 --tick 30
"""

import argparse
import threading
import webbrowser
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from core import (ServerClient, compute_supertrend, compute_aest,
                  compute_jma_trend, compute_tick_intensity, build_html)
from filters import FILTER_REGISTRY


# ═══════════════════════════════════════════════════════════════
#  타임프레임 정의
# ═══════════════════════════════════════════════════════════════
TF_OPTIONS = ["D", "m1", "m3", "m5", "m10", "m15", "m30", "m60"]


def parse_tf(tf_str):
    tf_str = tf_str.strip()
    if tf_str == "D":
        return "일봉", 0
    elif tf_str.startswith("m"):
        try:
            return f"{int(tf_str[1:])}분봉", int(tf_str[1:])
        except ValueError:
            pass
    return "일봉", 0


# ═══════════════════════════════════════════════════════════════
#  설정 & 캐시
# ═══════════════════════════════════════════════════════════════
CFG = {
    "host": "localhost", "port": 8082, "chart_port": 9090,
    "atr_len": 14, "base_mult": 3.0,
    "default_code": "005930", "default_tf": "D",
    "default_filter": "None", "default_date": "",
    "default_tick": 0,
}

CACHE = {"key": None, "df_raw": None, "name": None}


def cache_key(code, tf_str, date_str):
    return f"{code}_{tf_str}_{date_str}"


def load_data(code, tf_str, date_str=""):
    key = cache_key(code, tf_str, date_str)
    if CACHE["key"] == key and CACHE["df_raw"] is not None:
        print(f"  캐시 사용: {code} {tf_str} {date_str}")
        return CACHE["df_raw"].copy(), CACHE["name"]

    client = ServerClient(CFG["host"], CFG["port"])
    print(f"\n  종목: {code}", end=" ")
    nm = client.symbol_name(code)
    print(nm)

    tf_label, tick = parse_tf(tf_str)
    print(f"  타임프레임: {tf_label}" + (f"  일자: {date_str}" if date_str else ""))

    if tick == 0:
        df = client.daily_candles(code)
    else:
        df = client.minute_candles_from(code, tick=tick, from_date=date_str)

    print("  Standard SuperTrend 계산...")
    df = compute_supertrend(df, CFG["atr_len"], CFG["base_mult"])

    CACHE["key"] = key
    CACHE["df_raw"] = df.copy()
    CACHE["name"] = nm
    return df, nm


def generate_chart(code, tf_str, filter_name, date_str="", tick_size=0):
    df, nm = load_data(code, tf_str, date_str)
    tf_label, tick_min = parse_tf(tf_str)

    # AEST 계산
    filter_func = FILTER_REGISTRY.get(filter_name, FILTER_REGISTRY["None"])
    df = compute_aest(df, CFG["atr_len"], CFG["base_mult"], filter_func)

    # JMA(7,50,2) 계산
    df = compute_jma_trend(df, length=7, phase=50, power=2)

    # 틱강도 계산 (분봉 + 틱캔들 선택 시)
    if tick_size > 0 and tick_min > 0:
        try:
            client = ServerClient(CFG["host"], CFG["port"])
            if date_str:
                stop = date_str.replace("-", "") + "090000"
            else:
                stop = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d") + "090000"
            df_tick = client.tick_candles(code, tick=tick_size, stop_time=stop)
            df = compute_tick_intensity(df, df_tick, tick_size)
            print(f"  틱강도 계산 완료 ({tick_size}틱)")
        except Exception as e:
            print(f"  틱강도 계산 실패: {e}")

    # 통계 출력
    sa = df["st_trend"].dropna().values
    st_flips = sum(1 for i in range(1, len(sa)) if sa[i] != sa[i-1])
    aa = df["aest_trend"].dropna().values
    aest_flips = sum(1 for i in range(1, len(aa)) if aa[i] != aa[i-1])
    reduction = round((1 - aest_flips / max(st_flips, 1)) * 100)
    range_bars = int(df["aest_is_range"].sum())
    range_pct = round(range_bars / len(df) * 100, 1)

    print(f"\n  ── {code} {nm} [{tf_label}] 필터:{filter_name} ──")
    print(f"  ST전환: {st_flips}회  AEST전환: {aest_flips}회 ({reduction}% 감소)")
    print(f"  횡보구간: {range_bars}봉 ({range_pct}%)")
    if "jma_trend" in df.columns:
        jt = df["jma_trend"].values
        jma_flips = sum(1 for i in range(1, len(jt)) if jt[i] != jt[i-1] and jt[i] != 0)
        print(f"  JMA전환: {jma_flips}회")
    if "tick_intensity" in df.columns:
        avg_ti = df["tick_intensity"].mean()
        max_ti = df["tick_intensity"].max()
        print(f"  틱강도: 평균={avg_ti:.1f} 최대={max_ti} ({tick_size}틱)")

    html = build_html(df, code, nm, tf_label, filter_name,
                      list(FILTER_REGISTRY.keys()), TF_OPTIONS, tf_str, date_str,
                      tick_size=tick_size)
    return html


# ═══════════════════════════════════════════════════════════════
#  HTTP
# ═══════════════════════════════════════════════════════════════
class ChartHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        code = params.get("code", [CFG["default_code"]])[0].strip()
        tf = params.get("tf", [CFG["default_tf"]])[0].strip()
        flt = params.get("filter", [CFG["default_filter"]])[0].strip()
        date = params.get("date", [CFG["default_date"]])[0].strip()
        tick_size = int(params.get("tick", [str(CFG["default_tick"])])[0])

        if flt not in FILTER_REGISTRY:
            flt = "None"
        if tf not in TF_OPTIONS:
            tf = "D"
        if tf == "D":
            date = ""
            tick_size = 0

        try:
            html = generate_chart(code, tf, flt, date, tick_size)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            err = ('<!DOCTYPE html><html><body style="background:#131722;color:#ef5350;'
                   'font-family:monospace;padding:40px;">'
                   '<h2>\uc624\ub958</h2><p>' + str(e) + '</p>'
                   '<a href="/" style="color:#2962ff;">\ub3cc\uc544\uac00\uae30</a></body></html>')
            self.wfile.write(err.encode("utf-8"))

    def log_message(self, *a):
        pass


# ═══════════════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="AEST Chart Viewer")
    parser.add_argument("code", nargs="?", default="005930")
    parser.add_argument("--tf", default="D")
    parser.add_argument("--filter", default="None")
    parser.add_argument("--date", default="")
    parser.add_argument("--tick", type=int, default=0, help="틱캔들 크기 (0=없음, 15/30/60/120)")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument("--chart_port", type=int, default=9090)
    parser.add_argument("--atr_len", type=int, default=14)
    parser.add_argument("--base_mult", type=float, default=3.0)
    args = parser.parse_args()

    CFG.update({
        "host": args.host, "port": args.port, "chart_port": args.chart_port,
        "atr_len": args.atr_len, "base_mult": args.base_mult,
        "default_code": args.code, "default_tf": args.tf,
        "default_filter": args.filter, "default_date": args.date,
        "default_tick": args.tick,
    })

    print("=" * 60)
    print("  AEST Chart Viewer")
    print("=" * 60)
    print(f"  서버: {CFG['host']}:{CFG['port']}")
    print(f"  필터: {list(FILTER_REGISTRY.keys())}")
    print(f"  타임프레임: {TF_OPTIONS}")
    print(f"  틱캔들: {args.tick}")

    server = HTTPServer(("0.0.0.0", args.chart_port), ChartHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    url = f"http://localhost:{args.chart_port}/?code={args.code}&tf={args.tf}&filter={args.filter}"
    if args.date:
        url += f"&date={args.date}"
    if args.tick > 0:
        url += f"&tick={args.tick}"
    print(f"\n  차트: {url}")
    webbrowser.open(url)

    print("  Ctrl+C 종료\n")
    try:
        t.join()
    except KeyboardInterrupt:
        print("\n  종료!")
        server.shutdown()


if __name__ == "__main__":
    main()
