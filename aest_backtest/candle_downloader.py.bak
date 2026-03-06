"""
캔들 다운로더 — 기존 server32 (localhost:8082) API → aest_db 캐시

서버 엔드포인트:
  GET /api/market/candles/minute?code={code}&tick=1&stopTime=yyyyMMddHHmmss
  GET /api/market/candles/tick?code={code}&tick=30&stopTime=yyyyMMddHHmmss

stopTime = 이 시점부터 데이터 조회 시작
  → 당일 전체 데이터: stopTime = 당일 090000
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from datetime import date, datetime
from typing import List
from aest_config import SERVER_BASE
from aest_db import AestDB


class CandleDownloader:

    def __init__(self):
        self.db = AestDB()
        self.base = SERVER_BASE

    # ──────── 캐시 유효성 검사 ────────

    def _has_valid_minute(self, code: str, target_date: date) -> bool:
        rows = self.db.get_minute(code, target_date, "09:00:00", "09:05:00")
        return len(rows) > 0

    def _has_valid_tick30(self, code: str, target_date: date) -> bool:
        rows = self.db.get_tick30(code, target_date)
        return len(rows) > 0

    # ──────── 분봉 ────────

    def download_minute(self, code: str, target_date: date) -> int:
        if self._has_valid_minute(code, target_date):
            return 0

        stop_time = f"{target_date.strftime('%Y%m%d')}090000"
        url = (f"{self.base}/api/market/candles/minute"
               f"?code={code}&tick=1&stopTime={stop_time}")

        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 404:
                return -1
            resp.raise_for_status()
            result = resp.json()
        except requests.exceptions.HTTPError:
            return -1
        except Exception as e:
            print(f"\n    ⚠ 분봉 통신오류 {code}: {e}")
            return -1

        if not result.get("Success") or not result.get("Data"):
            return 0

        target_str = target_date.strftime("%Y%m%d")
        rows = []
        for r in result["Data"]:
            ts = str(r.get("체결시간", ""))
            if not ts.startswith(target_str):
                continue

            dt_val = datetime.strptime(ts[:8], "%Y%m%d").date()
            tm = f"{ts[8:10]}:{ts[10:12]}:00"
            rows.append({
                "dt": dt_val,
                "tm": tm,
                "open": abs(int(r.get("시가", 0))),
                "high": abs(int(r.get("고가", 0))),
                "low": abs(int(r.get("저가", 0))),
                "close": abs(int(r.get("현재가", 0))),
                "volume": abs(int(r.get("거래량", 0))),
            })

        if rows:
            self.db.insert_minute(code, rows)
            self.db.log_download(code, "minute", target_date, len(rows))
        return len(rows)

    # ──────── 30틱 ────────

    def download_tick30(self, code: str, target_date: date) -> int:
        if self._has_valid_tick30(code, target_date):
            return 0

        stop_time = f"{target_date.strftime('%Y%m%d')}090000"
        url = (f"{self.base}/api/market/candles/tick"
               f"?code={code}&tick=30&stopTime={stop_time}")

        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 404:
                return -1
            resp.raise_for_status()
            result = resp.json()
        except requests.exceptions.HTTPError:
            return -1
        except Exception as e:
            print(f"\n    ⚠ 30틱 통신오류 {code}: {e}")
            return -1

        if not result.get("Success") or not result.get("Data"):
            return 0

        target_str = target_date.strftime("%Y%m%d")
        rows = []
        seq = 0
        for r in result["Data"]:
            ts = str(r.get("체결시간", ""))
            if not ts.startswith(target_str):
                continue

            seq += 1
            dt_val = datetime.strptime(ts[:8], "%Y%m%d").date()
            tm = f"{ts[8:10]}:{ts[10:12]}:00"
            rows.append({
                "dt": dt_val,
                "tm": tm,
                "seq": seq,
                "open": abs(int(r.get("시가", 0))),
                "high": abs(int(r.get("고가", 0))),
                "low": abs(int(r.get("저가", 0))),
                "close": abs(int(r.get("현재가", 0))),
                "volume": abs(int(r.get("거래량", 0))),
            })

        if rows:
            self.db.insert_tick30(code, rows)
            self.db.log_download(code, "tick30", target_date, len(rows))
        return len(rows)

    # ──────── 종목 일괄 ────────

    def download_all(self, code: str, target_date: date) -> dict:
        return {
            "minute": self.download_minute(code, target_date),
            "tick30": self.download_tick30(code, target_date),
        }

    def download_batch(self, codes: List[str], target_date: date):
        total = {"minute": 0, "tick30": 0, "fail": 0}
        for i, code in enumerate(codes, 1):
            print(f"  [{i}/{len(codes)}] {code} ...", end=" ")
            r = self.download_all(code, target_date)

            labels = []
            for k in ("minute", "tick30"):
                v = r[k]
                if v == 0:
                    labels.append(f"{k}=캐시")
                elif v == -1:
                    labels.append(f"{k}=404")
                    total["fail"] += 1
                else:
                    labels.append(f"{k}={v}건")
                    total[k] += v
            print("  ".join(labels))

        print(f"\n  합계: 분봉={total['minute']}건  30틱={total['tick30']}건  "
              f"404={total['fail']}건")
        print(f"  (일봉은 기존 stock_info.daily_candles 사용)")
        return total
