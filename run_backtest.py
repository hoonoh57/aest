"""
E:\2026\aest\run_backtest.py — CLI 진입점

사용법:
  python run_backtest.py --date 20260304                  # 내장 샘플
  python run_backtest.py --date 20260304 --file data.txt  # 파일에서
  python run_backtest.py --date 20260304 --clipboard      # 클립보드에서
  python run_backtest.py --date 20260304 --reanalyze      # DB 재분석
  python run_backtest.py --reanalyze-all                  # 전체 재분석
"""

import sys
import os
import argparse
from datetime import datetime

# 현재 디렉토리를 sys.path 최상위에
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from aest_backtest.runner import BacktestRunner

# 내장 샘플 (03/04 성과검증 데이터)
SAMPLE_TEXT = """종목명\t기간\t수익률\t최고수익률\t거래량
한일사료\t09:05~16:00\t+7.18\t+14.23\t2587654
APS홀딩스\t09:05~16:00\t-5.91\t+13.11\t266472
성호전자\t09:05~16:00\t-2.31\t+6.75\t4832109
지에스이\t09:05~16:00\t+3.42\t+8.19\t1923847
파이버프로\t09:05~16:00\t-8.43\t+4.12\t312456
홀릭스\t09:05~16:00\t-6.78\t+2.91\t189234
"""


def main():
    parser = argparse.ArgumentParser(description="AEST BacktestRunner")
    parser.add_argument("--date", type=str, help="포착일 YYYYMMDD")
    parser.add_argument("--file", type=str, help="클립보드 텍스트 파일 경로")
    parser.add_argument("--clipboard", action="store_true",
                        help="클립보드에서 읽기 (pyperclip)")
    parser.add_argument("--reanalyze", action="store_true",
                        help="DB 데이터만으로 재분석 (다운로드 없이)")
    parser.add_argument("--reanalyze-all", action="store_true",
                        help="저장된 모든 날짜 재분석")
    args = parser.parse_args()

    runner = BacktestRunner()

    # ── 전체 재분석 ──
    if args.reanalyze_all:
        runner.reanalyze_all()
        return

    # ── 날짜 필수 ──
    if not args.date:
        print("사용법:")
        print("  python run_backtest.py --date 20260304")
        print("  python run_backtest.py --date 20260304 --file data.txt")
        print("  python run_backtest.py --date 20260304 --clipboard")
        print("  python run_backtest.py --date 20260304 --reanalyze")
        print("  python run_backtest.py --reanalyze-all")
        sys.exit(1)

    capture_date = datetime.strptime(args.date, "%Y%m%d").date()

    # ── 재분석 모드 ──
    if args.reanalyze:
        runner.reanalyze(capture_date)
        return

    # ── 텍스트 소스 결정 ──
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            raw_text = f.read()
    elif args.clipboard:
        try:
            import pyperclip
            raw_text = pyperclip.paste()
        except ImportError:
            print("pyperclip 미설치: pip install pyperclip")
            sys.exit(1)
    else:
        print("  (내장 샘플 데이터 사용)")
        raw_text = SAMPLE_TEXT

    # ── 전체 파이프라인 ──
    runner.run_full(raw_text, capture_date)


if __name__ == "__main__":
    main()
