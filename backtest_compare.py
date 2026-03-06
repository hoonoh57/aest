# backtest_compare.py
"""
현재 로직(누적점수) vs 강화 로직(AND필터) 동일 데이터 비교
"""
import pymysql
from datetime import date
from collections import defaultdict

def get_conn():
    return pymysql.connect(
        host='localhost', user='root', password='ms34469118',
        charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor
    )

def find_candidates(conn, target_date):
    sql = """
    SELECT 
        a.code,
        b.date AS signal_date, a.date AS trade_date,
        b.open AS prev_open, b.high AS prev_high, 
        b.low AS prev_low, b.close AS prev_close,
        b.volume AS prev_volume,
        c.close AS prev2_close, c.volume AS prev2_volume,
        c.open AS prev2_open,
        ROUND((b.close - c.close) / c.close * 100, 2) AS prev_return,
        ROUND(b.volume / c.volume, 1) AS vol_ratio,
        a.open AS today_open, a.high AS today_high,
        a.low AS today_low, a.close AS today_close,
        a.volume AS today_volume,
        ROUND((a.high - b.close) / b.close * 100, 2) AS max_return,
        ROUND((a.close - b.close) / b.close * 100, 2) AS close_return,
        ROUND((a.open - b.close) / b.close * 100, 2) AS gap_pct
    FROM stock_info.daily_candles a
    JOIN stock_info.daily_candles b 
        ON a.code = b.code AND b.date = (
            SELECT MAX(date) FROM stock_info.daily_candles 
            WHERE code = a.code AND date < a.date
        )
    JOIN stock_info.daily_candles c
        ON b.code = c.code AND c.date = (
            SELECT MAX(date) FROM stock_info.daily_candles 
            WHERE code = b.code AND date < b.date
        )
    WHERE a.date = %s
        AND b.close > c.close
        AND ROUND((b.close - c.close) / c.close * 100, 2) >= 5
        AND b.volume > c.volume * 2
    ORDER BY prev_return DESC
    LIMIT 60
    """
    with conn.cursor() as cur:
        cur.execute(sql, (target_date,))
        return cur.fetchall()

def get_daily_5d(conn, code, target_date):
    sql = """
    SELECT date, open, high, low, close, volume
    FROM stock_info.daily_candles
    WHERE code = %s AND date < %s
    ORDER BY date DESC LIMIT 5
    """
    with conn.cursor() as cur:
        cur.execute(sql, (code, target_date))
        return cur.fetchall()

def calc_metrics(row, daily_5d):
    prev_close = row['prev_close']
    prev_open = row['prev_open']
    prev_high = row['prev_high']
    prev_low = row['prev_low']
    gap = row['gap_pct']

    candle_range = prev_high - prev_low
    body_top = max(prev_open, prev_close)
    wick = (prev_high - body_top) / candle_range if candle_range > 0 else 0
    cpos = (prev_close - prev_low) / candle_range if candle_range > 0 else 0.5

    bearish = 0
    for d in daily_5d[1:]:
        if d['close'] < d['open']:
            bearish += 1
        else:
            break

    if daily_5d:
        best_close = max(d['close'] for d in daily_5d[:5])
        div = (prev_close - best_close) / best_close * 100
    else:
        div = 0

    # 5분 거래대금 추정 (일봉 거래대금의 약 3%)
    daily_amount = prev_close * row['prev_volume']
    est_5min_eok = daily_amount * 0.03 / 1e8

    return {
        'gap': gap, 'wick': round(wick, 2), 'cpos': round(cpos, 2),
        'bearish': bearish, 'div': round(div, 1),
        'vol_ratio': row['vol_ratio'], 'est_5min': round(est_5min_eok, 1),
        'prev_return': row['prev_return']
    }

def filter_current(row, m):
    """현재 로직: 누적 점수 방식"""
    score = 0
    if m['gap'] >= 10.0:
        return 100, "BLOCK"
    if m['est_5min'] < 1.0:
        score += 30
    elif m['est_5min'] < 10.0:
        score += 10
    if m['gap'] >= 7.0:
        score += 15
    elif m['gap'] >= 4.0:
        score += 5
    if m['wick'] >= 0.6:
        score += 10
    if m['cpos'] <= 0.2 or m['cpos'] >= 0.9:
        score += 10
    if m['bearish'] >= 3:
        score += 10
    if (m['vol_ratio'] or 0) >= 3.0 and m['gap'] >= 3.0:

        score += 10

    if score >= 35:
        return score, "BLOCK"
    elif score >= 20:
        return score, "CAUTION"
    else:
        return score, "PASS"

def filter_strict(row, m):
    """강화 로직: 7개 AND 필터"""
    f1 = m['gap'] < 10.0
    f2 = m['est_5min'] >= 10.0
    f3 = m['wick'] < 0.5
    f4 = m['bearish'] < 3
    f5 = 0.3 < m['cpos'] < 0.8
    f6 = m['div'] > -8.0
    f7 = m['est_5min'] < 300.0

    passed = f1 and f2 and f3 and f4 and f5 and f6 and f7
    return passed

def classify(row):
    max_ret = row['max_return']
    close_ret = row['close_return']
    if max_ret >= 10:
        return "WINNER"
    elif max_ret >= 5:
        return "GOOD" if close_ret >= 0 else "TRAP"
    elif close_ret < 0:
        return "LOSER"
    else:
        return "NORMAL"

def run():
    conn = get_conn()
    trading_days = [
        date(2026,2,19), date(2026,2,20),
        date(2026,2,23), date(2026,2,24), date(2026,2,25),
        date(2026,2,26), date(2026,2,27),
        date(2026,3,3), date(2026,3,4), date(2026,3,5),
    ]

    # 현재 로직 통계
    cur_stats = defaultdict(int)
    # 강화 로직 통계
    str_stats = defaultdict(int)

    print("=" * 150)
    print(f"{'날짜':12s} | {'--- 현재 로직 (누적점수) ---':^40s} | {'--- 강화 로직 (AND필터) ---':^40s} |")
    print(f"{'':12s} | {'포착':>4s} {'PASS':>5s} {'W':>3s} {'G':>3s} {'T':>3s} {'L':>3s} {'정밀':>5s} {'차단':>5s} | {'통과':>4s} {'W':>3s} {'G':>3s} {'T':>3s} {'L':>3s} {'정밀':>5s} {'차단':>5s} |")
    print("-" * 150)

    for td in trading_days:
        candidates = find_candidates(conn, td)
        if not candidates:
            print(f"{td}  포착 0건")
            continue

        total = len(candidates)
        # 현재 로직
        c = defaultdict(int)
        c['total'] = total
        # 강화 로직
        s = defaultdict(int)
        s['total'] = total

        for row in candidates:
            daily_5d = get_daily_5d(conn, row['code'], td)
            label = classify(row)
            m = calc_metrics(row, daily_5d)
            is_mine = label in ("TRAP", "LOSER")

            # 현재 로직
            score, verdict = filter_current(row, m)
            c[f'{label}_total'] += 1
            if is_mine:
                c['mine_total'] += 1
            if verdict == "PASS":
                c['pass'] += 1
                c[f'{label}_pass'] += 1
                if is_mine:
                    c['mine_pass'] += 1

            # 강화 로직
            passed = filter_strict(row, m)
            s[f'{label}_total'] += 1
            if is_mine:
                s['mine_total'] += 1
            if passed:
                s['pass'] += 1
                s[f'{label}_pass'] += 1
                if is_mine:
                    s['mine_pass'] += 1

        # 일일 KPI
        c_prec = c['WINNER_pass'] / c['pass'] * 100 if c['pass'] > 0 else 0
        c_block = (c['mine_total'] - c['mine_pass']) / c['mine_total'] * 100 if c['mine_total'] > 0 else 100

        s_prec = s['WINNER_pass'] / s['pass'] * 100 if s['pass'] > 0 else 0
        s_block = (s['mine_total'] - s['mine_pass']) / s['mine_total'] * 100 if s['mine_total'] > 0 else 100

        print(f"{td}  | {total:>4d} {c['pass']:>5d} {c['WINNER_pass']:>3d} {c['GOOD_pass']:>3d} {c['TRAP_pass']:>3d} {c['LOSER_pass']:>3d} {c_prec:>4.0f}% {c_block:>4.0f}% | {s['pass']:>4d} {s['WINNER_pass']:>3d} {s['GOOD_pass']:>3d} {s['TRAP_pass']:>3d} {s['LOSER_pass']:>3d} {s_prec:>4.0f}% {s_block:>4.0f}% |")

        for k in c:
            cur_stats[k] += c[k]
        for k in s:
            str_stats[k] += s[k]

    # 종합
    print("=" * 150)
    c, s = cur_stats, str_stats
    c_prec = c['WINNER_pass'] / c['pass'] * 100 if c['pass'] > 0 else 0
    c_block = (c['mine_total'] - c['mine_pass']) / c['mine_total'] * 100 if c['mine_total'] > 0 else 100
    s_prec = s['WINNER_pass'] / s['pass'] * 100 if s['pass'] > 0 else 0
    s_block = (s['mine_total'] - s['mine_pass']) / s['mine_total'] * 100 if s['mine_total'] > 0 else 100

    print(f"{'종합':12s}  | {c['total']:>4d} {c['pass']:>5d} {c['WINNER_pass']:>3d} {c['GOOD_pass']:>3d} {c['TRAP_pass']:>3d} {c['LOSER_pass']:>3d} {c_prec:>4.0f}% {c_block:>4.0f}% | {s['pass']:>4d} {s['WINNER_pass']:>3d} {s['GOOD_pass']:>3d} {s['TRAP_pass']:>3d} {s['LOSER_pass']:>3d} {s_prec:>4.0f}% {s_block:>4.0f}% |")

    print(f"\n{'='*60}")
    print(f"{'지표':20s} {'현재로직':>10s} {'강화로직':>10s}")
    print(f"{'-'*60}")
    print(f"{'일평균 PASS':20s} {c['pass']/10:>10.1f} {s['pass']/10:>10.1f}")
    print(f"{'WINNER 통과':20s} {c['WINNER_pass']:>10d} {s['WINNER_pass']:>10d}")
    print(f"{'지뢰 통과':20s} {c['mine_pass']:>10d} {s['mine_pass']:>10d}")
    print(f"{'통과 정밀도':20s} {c_prec:>9.1f}% {s_prec:>9.1f}%")
    print(f"{'지뢰 차단율':20s} {c_block:>9.1f}% {s_block:>9.1f}%")

    # 추정 수익 비교
    print(f"\n{'='*60}")
    print("추정 수익 비교 (PASS 종목 중 WINNER의 평균 max_return 적용)")
    print(f"{'현재로직':20s} WINNER {c['WINNER_pass']}건 통과, 지뢰 {c['mine_pass']}건 혼입")
    print(f"{'강화로직':20s} WINNER {s['WINNER_pass']}건 통과, 지뢰 {s['mine_pass']}건 혼입")

    conn.close()

if __name__ == "__main__":
    run()
