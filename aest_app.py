#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aest_app.py — AEST 차트 뷰어
  차트에서 종목코드, 타임프레임, 일자, 횡보필터 변경 가능

  python aest_app.py
  python aest_app.py 005930
  python aest_app.py 034020 --tf m5 --filter LonesomeTheBlue
"""

import argparse
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from core import ServerClient, compute_supertrend, compute_aest, build_html
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


def generate_chart(code, tf_str, filter_name, date_str=""):
    df, nm = load_data(code, tf_str, date_str)
    tf_label, _ = parse_tf(tf_str)

    filter_func = FILTER_REGISTRY.get(filter_name, FILTER_REGISTRY["None"])
    df = compute_aest(df, CFG["atr_len"], CFG["base_mult"], filter_func)

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

    html = build_html(df, code, nm, tf_label, filter_name,
                      list(FILTER_REGISTRY.keys()), TF_OPTIONS, tf_str, date_str)
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

        if flt not in FILTER_REGISTRY:
            flt = "None"
        if tf not in TF_OPTIONS:
            tf = "D"
        if tf == "D":
            date = ""

        try:
            html = generate_chart(code, tf, flt, date)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            err = f"""<!DOCTYPE html><html><body style="background:#131722;color:#ef5350;
                font-family:monospace;padding:40px;">
                <h2>오류</h2><p>{str(e)}</p>
                <a href="/" style="color:#2962ff;">돌아가기</a></body></html>"""
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
    })

    print("=" * 60)
    print("  AEST Chart Viewer")
    print("=" * 60)
    print(f"  서버: {CFG['host']}:{CFG['port']}")
    print(f"  필터: {list(FILTER_REGISTRY.keys())}")
    print(f"  타임프레임: {TF_OPTIONS}")

    server = HTTPServer(("0.0.0.0", args.chart_port), ChartHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    url = f"http://localhost:{args.chart_port}/?code={args.code}&tf={args.tf}&filter={args.filter}"
    if args.date:
        url += f"&date={args.date}"
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