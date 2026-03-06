"""E:\2026\aest\aest_config.py"""

import os
from dotenv import load_dotenv

# .env 로드
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ── 기존 서버 (이미 가동 중) ──
SERVER_BASE = os.getenv("SERVER_BASE", "http://localhost:8082")

# ── MySQL 공통 접속정보 ──
_DB_HOST = os.getenv("DB_HOST", "localhost")
_DB_PORT = int(os.getenv("DB_PORT", "3306"))
_DB_USER = os.getenv("DB_USER", "root")
_DB_PASS = os.getenv("DB_PASSWORD", "")

# ── DB 이름 ──
STOCK_INFO_DB = os.getenv("STOCK_INFO_DB", "stock_information")
DAILY_CANDLE_DB = os.getenv("DAILY_CANDLE_DB", "stock_info")

# ── 기존 DB (읽기 전용) ──
EXISTING_DB = {
    "host": _DB_HOST,
    "port": _DB_PORT,
    "user": _DB_USER,
    "password": _DB_PASS,
    "charset": "utf8mb4",
}

# ── 신규 DB (읽기/쓰기) ──
AEST_DB = {
    "host": _DB_HOST,
    "port": _DB_PORT,
    "user": _DB_USER,
    "password": _DB_PASS,
    "database": os.getenv("AEST_DB_NAME", "aest_db"),
    "charset": "utf8mb4",
}

# ── RiskFilterAgent 임계값 (AND 필터 방식) ──
THRESHOLDS = {
    # F1: 갭 상한 (%)
    "gap_max": 10.0,

    # F2: 최소 5분 거래대금 (억)
    "min_amount_5min": 10.0,

    # F3: 전일 윗꼬리비 상한
    "max_wick": 0.5,

    # F4: 연속음봉 상한 (일)
    "max_bearish": 3,

    # F5: 전일 종가위치 범위
    "cpos_low": 0.3,
    "cpos_high": 0.8,

    # F6: 5일 고점 괴리율 하한 (%)
    "min_div_5d": -8.0,

    # F7: 과열 거래대금 상한 (억)
    "max_amount_5min": 300.0,
}

# ── 성과 분류 기준 ──
PERFORMANCE = {
    "winner_min": 10.0,
    "good_min": 5.0,
    "loser_max": -3.0,
    "trap_max": -5.0,
}
