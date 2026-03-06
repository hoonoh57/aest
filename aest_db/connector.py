"""
aest_db 커넥터
- 종목마스터, 일봉: 기존 DB에서 읽기
- 분봉, 틱캔들, 포착, 판정, KPI: aest_db에서 읽기/쓰기
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymysql
import json
from datetime import date
from contextlib import contextmanager
from aest_config import EXISTING_DB, STOCK_INFO_DB, DAILY_CANDLE_DB, AEST_DB


class AestDB:

    # ═══════════ 커넥션 ═══════════

    @contextmanager
    def _existing(self, db_name):
        cfg = {**EXISTING_DB, "database": db_name}
        c = pymysql.connect(**cfg)
        try:
            yield c
        finally:
            c.close()

    @contextmanager
    def _aest(self):
        c = pymysql.connect(**AEST_DB)
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ═══════════ 종목 마스터 (기존 DB) ═══════════

    def find_code_by_name(self, name: str):
        with self._existing(STOCK_INFO_DB) as c:
            with c.cursor(pymysql.cursors.DictCursor) as cur:
                cur.execute(
                    "SELECT code, name, market, market_cap "
                    "FROM stock_base_info WHERE name=%s", (name.strip(),))
                return cur.fetchone()

    def get_stock_by_code(self, code: str):
        with self._existing(STOCK_INFO_DB) as c:
            with c.cursor(pymysql.cursors.DictCursor) as cur:
                cur.execute(
                    "SELECT code, name, market, market_cap, sector "
                    "FROM stock_base_info WHERE code=%s", (code,))
                return cur.fetchone()

    # ═══════════ 일봉 (기존 DB) ═══════════

    def get_daily(self, code: str, dt_from: date, dt_to: date):
        with self._existing(DAILY_CANDLE_DB) as c:
            with c.cursor(pymysql.cursors.DictCursor) as cur:
                cur.execute("""
                    SELECT date AS dt, open, high, low, close, volume
                    FROM daily_candles
                    WHERE code=%s AND date BETWEEN %s AND %s
                    ORDER BY date
                """, (code, dt_from, dt_to))
                return cur.fetchall()

    # ═══════════ 분봉 캐시 (aest_db) ═══════════

    def has_minute(self, code: str, dt: date) -> bool:
        with self._aest() as c:
            with c.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM candle_minute WHERE code=%s AND dt=%s LIMIT 1",
                    (code, dt))
                return cur.fetchone() is not None

    def get_minute(self, code: str, dt: date,
                   tm_from="09:00:00", tm_to="15:30:00"):
        with self._aest() as c:
            with c.cursor(pymysql.cursors.DictCursor) as cur:
                cur.execute("""
                    SELECT dt, tm, open, high, low, close, volume
                    FROM candle_minute
                    WHERE code=%s AND dt=%s AND tm BETWEEN %s AND %s
                    ORDER BY tm
                """, (code, dt, tm_from, tm_to))
                return cur.fetchall()

    def insert_minute(self, code: str, rows: list):
        if not rows:
            return
        with self._aest() as c:
            with c.cursor() as cur:
                cur.executemany("""
                    INSERT IGNORE INTO candle_minute
                      (code, dt, tm, open, high, low, close, volume)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """, [(code, r['dt'], r['tm'], r['open'], r['high'],
                       r['low'], r['close'], r['volume']) for r in rows])

    # ═══════════ 30틱 캐시 (aest_db) ═══════════

    def has_tick30(self, code: str, dt: date) -> bool:
        with self._aest() as c:
            with c.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM candle_tick30 WHERE code=%s AND dt=%s LIMIT 1",
                    (code, dt))
                return cur.fetchone() is not None

    def get_tick30(self, code: str, dt: date):
        with self._aest() as c:
            with c.cursor(pymysql.cursors.DictCursor) as cur:
                cur.execute("""
                    SELECT seq, dt, tm, open, high, low, close, volume
                    FROM candle_tick30 WHERE code=%s AND dt=%s ORDER BY seq
                """, (code, dt))
                return cur.fetchall()

    def insert_tick30(self, code: str, rows: list):
        if not rows:
            return
        with self._aest() as c:
            with c.cursor() as cur:
                cur.executemany("""
                    INSERT IGNORE INTO candle_tick30
                      (code, dt, tm, seq, open, high, low, close, volume)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, [(code, r['dt'], r['tm'], r['seq'], r['open'], r['high'],
                       r['low'], r['close'], r['volume']) for r in rows])

    # ═══════════ caught_stocks ═══════════

    def insert_caught(self, rows: list):
        if not rows:
            return
        with self._aest() as c:
            with c.cursor() as cur:
                cur.executemany("""
                    INSERT IGNORE INTO caught_stocks
                      (capture_date, code, name, return_1m, return_3m,
                       return_7h, max_return, volume_krw, raw_text)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, [(r['capture_date'], r['code'], r['name'],
                       r.get('return_1m'), r.get('return_3m'),
                       r.get('return_7h'), r.get('max_return'),
                       r.get('volume_krw'), r.get('raw_text')) for r in rows])

    def get_caught(self, capture_date: date):
        with self._aest() as c:
            with c.cursor(pymysql.cursors.DictCursor) as cur:
                cur.execute(
                    "SELECT * FROM caught_stocks WHERE capture_date=%s ORDER BY id",
                    (capture_date,))
                return cur.fetchall()

    def get_all_caught_dates(self):
        with self._aest() as c:
            with c.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT capture_date FROM caught_stocks "
                    "ORDER BY capture_date")
                return [r[0] for r in cur.fetchall()]

    # ═══════════ agent_verdict ═══════════

    def upsert_verdict(self, v: dict):
        with self._aest() as c:
            with c.cursor() as cur:
                cur.execute("""
                    INSERT INTO agent_verdict
                      (capture_date, code, risk_score, verdict,
                       score_volume, score_gap, score_early, score_cap,
                       score_wick, score_volratio, score_closepos, score_bearish,
                       evidence)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                      risk_score=VALUES(risk_score), verdict=VALUES(verdict),
                      score_volume=VALUES(score_volume), score_gap=VALUES(score_gap),
                      score_early=VALUES(score_early), score_cap=VALUES(score_cap),
                      score_wick=VALUES(score_wick), score_volratio=VALUES(score_volratio),
                      score_closepos=VALUES(score_closepos),
                      score_bearish=VALUES(score_bearish),
                      evidence=VALUES(evidence)
                """, (v['capture_date'], v['code'], v['risk_score'], v['verdict'],
                      v.get('score_volume', 0), v.get('score_gap', 0),
                      v.get('score_early', 0), v.get('score_cap', 0),
                      v.get('score_wick', 0), v.get('score_volratio', 0),
                      v.get('score_closepos', 0), v.get('score_bearish', 0),
                      v.get('evidence')))

    def update_verdict_actual(self, capture_date, code,
                               max_ret, close_ret, label, is_correct):
        with self._aest() as c:
            with c.cursor() as cur:
                cur.execute("""
                    UPDATE agent_verdict
                    SET actual_max_ret=%s, actual_close_ret=%s,
                        actual_label=%s, is_correct=%s
                    WHERE capture_date=%s AND code=%s
                """, (max_ret, close_ret, label,
                      1 if is_correct else 0, capture_date, code))

    def get_verdicts(self, capture_date: date):
        with self._aest() as c:
            with c.cursor(pymysql.cursors.DictCursor) as cur:
                cur.execute(
                    "SELECT * FROM agent_verdict "
                    "WHERE capture_date=%s ORDER BY risk_score DESC",
                    (capture_date,))
                return cur.fetchall()

    # ═══════════ daily_kpi ═══════════

    def upsert_kpi(self, kpi: dict):
        with self._aest() as c:
            with c.cursor() as cur:
                cur.execute("""
                    INSERT INTO daily_kpi
                      (capture_date, total_caught, a_pass_count, a_block_count,
                       a_caution_count, winner_count, loser_count, trap_count,
                       block_accuracy, pass_safety, pass_winner_rate,
                       mine_block_rate, thresholds_ver)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                      total_caught=VALUES(total_caught),
                      a_pass_count=VALUES(a_pass_count),
                      a_block_count=VALUES(a_block_count),
                      a_caution_count=VALUES(a_caution_count),
                      winner_count=VALUES(winner_count),
                      loser_count=VALUES(loser_count),
                      trap_count=VALUES(trap_count),
                      block_accuracy=VALUES(block_accuracy),
                      pass_safety=VALUES(pass_safety),
                      pass_winner_rate=VALUES(pass_winner_rate),
                      mine_block_rate=VALUES(mine_block_rate),
                      thresholds_ver=VALUES(thresholds_ver)
                """, (kpi['capture_date'], kpi['total_caught'],
                      kpi['a_pass_count'], kpi['a_block_count'],
                      kpi['a_caution_count'], kpi['winner_count'],
                      kpi['loser_count'], kpi['trap_count'],
                      kpi.get('block_accuracy'), kpi.get('pass_safety'),
                      kpi.get('pass_winner_rate'), kpi.get('mine_block_rate'),
                      kpi.get('thresholds_ver')))

    # ═══════════ download_log ═══════════

    def has_downloaded(self, code: str, candle_type: str, dt: date) -> bool:
        with self._aest() as c:
            with c.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM download_log "
                    "WHERE code=%s AND candle_type=%s AND dt=%s LIMIT 1",
                    (code, candle_type, dt))
                return cur.fetchone() is not None

    def log_download(self, code: str, candle_type: str, dt: date, row_count: int):
        with self._aest() as c:
            with c.cursor() as cur:
                cur.execute("""
                    INSERT INTO download_log (code, candle_type, dt, row_count)
                    VALUES (%s,%s,%s,%s)
                """, (code, candle_type, dt, row_count))
