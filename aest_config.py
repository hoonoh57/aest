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

# ── RiskFilterAgent 임계값 ──
THRESHOLDS = {
    "vol_5min_danger": 1_0000_0000,
    "vol_5min_warning": 3_0000_0000,
    "gap_huge": 10.0,
    "gap_large": 7.0,
    "early_move_danger": 8.0,
    "early_move_warning": 5.0,
    "tiny_cap": 500_0000_0000,
    "wick_ratio_danger": 0.5,
    "vol_ratio_spike": 5.0,
    "close_pos_low": 0.2,
    "bearish_count": 4,
    "block_threshold": 40,
    "caution_threshold": 25,
}

# ── 성과 분류 기준 ──
PERFORMANCE = {
    "winner_min": 10.0,
    "good_min": 5.0,
    "loser_max": -3.0,
    "trap_max": -5.0,
}
