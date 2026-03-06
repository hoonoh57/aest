-- E:\2026\aest\aest_db\schema.sql
-- 실행: mysql -u root -p < E:\2026\aest\aest_db\schema.sql

CREATE DATABASE IF NOT EXISTS aest_db
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE aest_db;

-- ── 분봉 캐시 ──
CREATE TABLE IF NOT EXISTS candle_minute (
    code   VARCHAR(10) NOT NULL,
    dt     DATE        NOT NULL,
    tm     TIME        NOT NULL,
    open   INT         NOT NULL,
    high   INT         NOT NULL,
    low    INT         NOT NULL,
    close  INT         NOT NULL,
    volume BIGINT      NOT NULL,
    PRIMARY KEY (code, dt, tm),
    INDEX idx_code_dt (code, dt)
) ENGINE=InnoDB;

-- ── 30틱 캐시 ──
CREATE TABLE IF NOT EXISTS candle_tick30 (
    id     BIGINT      AUTO_INCREMENT,
    code   VARCHAR(10) NOT NULL,
    dt     DATE        NOT NULL,
    tm     TIME        NOT NULL,
    seq    INT         NOT NULL,
    open   INT         NOT NULL,
    high   INT         NOT NULL,
    low    INT         NOT NULL,
    close  INT         NOT NULL,
    volume BIGINT      NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_tick (code, dt, seq),
    INDEX idx_code_dt (code, dt)
) ENGINE=InnoDB;

-- ── 클립보드 포착 종목 ──
CREATE TABLE IF NOT EXISTS caught_stocks (
    id           INT          AUTO_INCREMENT,
    capture_date DATE         NOT NULL,
    code         VARCHAR(10)  NOT NULL,
    name         VARCHAR(40)  NOT NULL,
    return_1m    DECIMAL(6,2) DEFAULT NULL,
    return_3m    DECIMAL(6,2) DEFAULT NULL,
    return_7h    DECIMAL(6,2) DEFAULT NULL,
    max_return   DECIMAL(6,2) DEFAULT NULL,
    volume_krw   BIGINT       DEFAULT NULL,
    raw_text     TEXT         DEFAULT NULL,
    created_at   DATETIME     DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_date_code (capture_date, code),
    INDEX idx_date (capture_date)
) ENGINE=InnoDB;

-- ── 에이전트 판정 결과 ──
CREATE TABLE IF NOT EXISTS agent_verdict (
    id               INT          AUTO_INCREMENT,
    capture_date     DATE         NOT NULL,
    code             VARCHAR(10)  NOT NULL,
    risk_score       INT          NOT NULL,
    verdict          VARCHAR(10)  NOT NULL,
    score_volume     INT DEFAULT 0,
    score_gap        INT DEFAULT 0,
    score_early      INT DEFAULT 0,
    score_cap        INT DEFAULT 0,
    score_wick       INT DEFAULT 0,
    score_volratio   INT DEFAULT 0,
    score_closepos   INT DEFAULT 0,
    score_bearish    INT DEFAULT 0,
    evidence         JSON         DEFAULT NULL,
    actual_max_ret   DECIMAL(6,2) DEFAULT NULL,
    actual_close_ret DECIMAL(6,2) DEFAULT NULL,
    actual_label     VARCHAR(10)  DEFAULT NULL,
    is_correct       TINYINT(1)   DEFAULT NULL,
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_date_code (capture_date, code)
) ENGINE=InnoDB;

-- ── 일별 KPI ──
CREATE TABLE IF NOT EXISTS daily_kpi (
    capture_date     DATE NOT NULL,
    total_caught     INT DEFAULT 0,
    a_pass_count     INT DEFAULT 0,
    a_block_count    INT DEFAULT 0,
    a_caution_count  INT DEFAULT 0,
    winner_count     INT DEFAULT 0,
    loser_count      INT DEFAULT 0,
    trap_count       INT DEFAULT 0,
    block_accuracy   DECIMAL(5,2) DEFAULT NULL,
    pass_safety      DECIMAL(5,2) DEFAULT NULL,
    pass_winner_rate DECIMAL(5,2) DEFAULT NULL,
    mine_block_rate  DECIMAL(5,2) DEFAULT NULL,
    thresholds_ver   VARCHAR(20)  DEFAULT NULL,
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (capture_date)
) ENGINE=InnoDB;

-- ── 임계값 이력 ──
CREATE TABLE IF NOT EXISTS threshold_history (
    version            VARCHAR(20) NOT NULL,
    applied_date       DATE        NOT NULL,
    params             JSON        DEFAULT NULL,
    backtest_win_rate  DECIMAL(5,2) DEFAULT NULL,
    backtest_block_acc DECIMAL(5,2) DEFAULT NULL,
    status             VARCHAR(10) DEFAULT 'ACTIVE',
    created_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (version)
) ENGINE=InnoDB;

-- ── 다운로드 이력 ──
CREATE TABLE IF NOT EXISTS download_log (
    id          INT          AUTO_INCREMENT,
    code        VARCHAR(10)  NOT NULL,
    candle_type ENUM('minute','tick30') NOT NULL,
    dt          DATE         NOT NULL,
    row_count   INT DEFAULT 0,
    downloaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_code_type_dt (code, candle_type, dt)
) ENGINE=InnoDB;
