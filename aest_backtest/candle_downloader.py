"""
캔들 다운로더 — 기존 server32 (localhost:8082) API → aest_db 캐시

- 분봉 API: GET /api/market/candles/minute?code={code}&tick=1&stopTime=yyyymmddhhmmss
- 30틱 API: GET /api/market/candles/tick?code={code}&tick=30&stopTime=yyyymmddhhmmss
- stopTime 이후부터 현재까지 전부 반환 (최신→과거 역순)
- 지표 워밍업을 위해 전일 14:00부터 다운로드
"""

import sys, os, requests
from datetime import date, datetime, timedelta
from typing import List, Optional
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aest_config import SERVER_BASE
from aest_db import AestDB


class CandleDownloader:
    def __init__(self):
        self.db = AestDB()
        self.base = SERVER_BASE

    # ── 전일 영업일 계산 ──
    def _prev_business_day(self, d: date) -> date:
        """주말 건너뛰기 (공휴일은 DB 조회로 보완 가능)"""
        prev = d - timedelta(days=1)
        while prev.weekday() >= 5:  # 5=토, 6=일
            prev -= timedelta(days=1)
        return prev

    # ── 분봉 다운로드 ──
    def download_minute(self, code: str, target_date: date) -> int:
        if self._has_valid_cache(code, target_date, 'minute'):
            return 0

        prev_day = self._prev_business_day(target_date)
        stop_time = f"{prev_day.strftime('%Y%m%d')}140000"
        url = f"{self.base}/api/market/candles/minute?code={code}&tick=1&stopTime={stop_time}"

        try:
            resp = requests.get(url, timeout=60)
            if resp.status_code == 404:
                return -1
            resp.raise_for_status()
            result = resp.json()
        except Exception as e:
            print(f"    ⚠ 분봉 다운로드 실패 {code}: {e}")
            return -1

        if not result.get('Success') or not result.get('Data'):
            return 0

        # 전일 14:00 ~ 당일 15:30 구간 필터링
        prev_start = f"{prev_day.strftime('%Y%m%d')}140000"
        target_end = f"{target_date.strftime('%Y%m%d')}153000"

        rows_prev = []  # 전일 14:00~15:30 (워밍업)
        rows_target = []  # 당일 09:00~15:30

        for r in result['Data']:
            ts = str(r.get('체결시간', ''))
            if len(ts) < 12:
                continue

            dt_str = ts[:8]
            tm_str = f"{ts[8:10]}:{ts[10:12]}:00"
            dt = datetime.strptime(dt_str, '%Y%m%d').date()

            row = {
                'dt': dt,
                'tm': tm_str,
                'open': abs(int(r.get('시가', 0))),
                'high': abs(int(r.get('고가', 0))),
                'low':  abs(int(r.get('저가', 0))),
                'close': abs(int(r.get('현재가', 0))),
                'volume': abs(int(r.get('거래량', 0))),
            }

            if dt == prev_day and ts >= prev_start:
                rows_prev.append(row)
            elif dt == target_date and ts <= target_end:
                rows_target.append(row)

        # 전일 + 당일 모두 저장
        all_rows = rows_prev + rows_target
        if all_rows:
            self.db.insert_minute(code, all_rows)
            self.db.log_download(code, 'minute', target_date, len(all_rows))
        return len(all_rows)

    # ── 30틱 다운로드 ──
    def download_tick30(self, code: str, target_date: date) -> int:
        if self._has_valid_cache(code, target_date, 'tick30'):
            return 0

        prev_day = self._prev_business_day(target_date)
        stop_time = f"{prev_day.strftime('%Y%m%d')}140000"
        url = f"{self.base}/api/market/candles/tick?code={code}&tick=30&stopTime={stop_time}"

        try:
            resp = requests.get(url, timeout=60)
            if resp.status_code == 404:
                return -1
            resp.raise_for_status()
            result = resp.json()
        except Exception as e:
            print(f"    ⚠ 30틱 다운로드 실패 {code}: {e}")
            return -1

        if not result.get('Success') or not result.get('Data'):
            return 0

        prev_start = f"{prev_day.strftime('%Y%m%d')}140000"
        target_end = f"{target_date.strftime('%Y%m%d')}153000"

        rows_prev = []
        rows_target = []
        seq_prev = 0
        seq_target = 0

        # API는 최신→과거 순이므로 역순 정렬 후 seq 부여
        data_sorted = sorted(result['Data'],
                             key=lambda x: str(x.get('체결시간', '')))

        for r in data_sorted:
            ts = str(r.get('체결시간', ''))
            if len(ts) < 12:
                continue

            dt_str = ts[:8]
            tm_str = f"{ts[8:10]}:{ts[10:12]}:{ts[12:14] if len(ts)>=14 else '00'}"
            dt = datetime.strptime(dt_str, '%Y%m%d').date()

            if dt == prev_day and ts >= prev_start:
                seq_prev += 1
                rows_prev.append({
                    'dt': dt, 'tm': tm_str, 'seq': seq_prev,
                    'open': abs(int(r.get('시가', 0))),
                    'high': abs(int(r.get('고가', 0))),
                    'low':  abs(int(r.get('저가', 0))),
                    'close': abs(int(r.get('현재가', 0))),
                    'volume': abs(int(r.get('거래량', 0))),
                })
            elif dt == target_date and ts <= target_end:
                seq_target += 1
                rows_target.append({
                    'dt': dt, 'tm': tm_str, 'seq': seq_target,
                    'open': abs(int(r.get('시가', 0))),
                    'high': abs(int(r.get('고가', 0))),
                    'low':  abs(int(r.get('저가', 0))),
                    'close': abs(int(r.get('현재가', 0))),
                    'volume': abs(int(r.get('거래량', 0))),
                })

        all_rows = rows_prev + rows_target
        if all_rows:
            self.db.insert_tick30(code, all_rows)
            self.db.log_download(code, 'tick30', target_date, len(all_rows))
        return len(all_rows)

    # ── 캐시 유효성 검사 ──
    def _has_valid_cache(self, code: str, target_date: date, candle_type: str) -> bool:
        """당일 데이터가 최소 10건 이상 있어야 유효한 캐시"""
        if candle_type == 'minute':
            if not self.db.has_minute(code, target_date):
                return False
            rows = self.db.get_minute(code, target_date)
            return len(rows) >= 10
        else:
            if not self.db.has_tick30(code, target_date):
                return False
            rows = self.db.get_tick30(code, target_date)
            return len(rows) >= 10

    # ── 종목 일괄 ──
    def download_all(self, code: str, target_date: date) -> dict:
        return {
            'minute': self.download_minute(code, target_date),
            'tick30': self.download_tick30(code, target_date),
        }

    def download_batch(self, codes: List[str], target_date: date):
        prev_day = self._prev_business_day(target_date)
        print(f"  워밍업 구간: {prev_day} 14:00 ~ {target_date} 15:30")
        total = {'minute': 0, 'tick30': 0}
        for i, code in enumerate(codes, 1):
            print(f"  [{i}/{len(codes)}] {code} ...", end=' ')
            r = self.download_all(code, target_date)
            total['minute'] += max(r['minute'], 0)
            total['tick30'] += max(r['tick30'], 0)
            labels = []
            for k in ('minute', 'tick30'):
                if r[k] == 0:
                    labels.append(f"{k}=캐시")
                elif r[k] == -1:
                    labels.append(f"{k}=실패")
                else:
                    labels.append(f"{k}={r[k]}건")
            print("  ".join(labels))
        print(f"\n  합계: 분봉={total['minute']}  30틱={total['tick30']}")
        print(f"  (일봉은 기존 stock_info.daily_candles 사용)")
        return total
