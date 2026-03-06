"""
BacktestRunner — 전체 파이프라인 오케스트레이션

STEP 1: 클립보드 텍스트 → caught_stocks 저장
STEP 2: 포착 종목 분봉/30틱 다운로드 → aest_db 캐시
STEP 3: RiskFilterAgent 판정 → agent_verdict 저장
STEP 4: KPI 집계 → daily_kpi 저장
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from datetime import date
from aest_config import PERFORMANCE
from aest_db import AestDB
from aest_backtest.clipboard_parser import ClipboardParser
from aest_backtest.candle_downloader import CandleDownloader
from aest_backtest.data_collector import DataCollector
from aest_backtest.risk_filter_agent import RiskFilterAgent


class BacktestRunner:

    def __init__(self):
        self.db = AestDB()
        self.downloader = CandleDownloader()
        self.collector = DataCollector(self.db)
        self.agent = RiskFilterAgent()

    # ══════════ STEP 1: 클립보드 → DB ══════════

    def import_clipboard(self, raw_text: str, capture_date: date) -> int:
        parser = ClipboardParser()
        parsed = parser.parse(raw_text)
        rows = []
        for p in parsed:
            info = self.db.find_code_by_name(p["name"])
            if not info:
                print(f"  ⚠ '{p['name']}' 코드 미발견")
                continue
            rows.append({
                "capture_date": capture_date,
                "code": info["code"],
                "name": p["name"],
                "return_1m": p.get("return_1m"),
                "return_3m": p.get("return_3m"),
                "return_7h": p.get("return_7h"),
                "max_return": p.get("max_return"),
                "volume_krw": p.get("volume_krw"),
                "raw_text": p.get("raw_text"),
            })
        self.db.insert_caught(rows)
        print(f"  ✅ {len(rows)}건 caught_stocks 저장")
        return len(rows)

    # ══════════ STEP 2: 캔들 다운로드 ══════════

    def download_candles(self, capture_date: date):
        caught = self.db.get_caught(capture_date)
        codes = [c["code"] for c in caught]
        if not codes:
            print("  ⚠ 포착 종목 없음")
            return
        print(f"\n  캔들 다운로드: {capture_date} / {len(codes)}종목")
        self.downloader.download_batch(codes, capture_date)

    # ══════════ STEP 3: 에이전트 판정 ══════════

    def run_agent(self, capture_date: date):
        caught = self.db.get_caught(capture_date)
        if not caught:
            print("  ⚠ 포착 종목 없음")
            return

        print(f"\n  RiskFilterAgent 판정: {capture_date}")
        print(f"  {'─'*55}")

        for c in caught:
            code, name = c["code"], c["name"]

            data = self.collector.collect(code, capture_date)
            if data is None:
                print(f"  ⚠ {name}({code}) 데이터 부족")
                continue

            risk = self.agent.evaluate(data)

            max_ret = float(c["max_return"]) if c["max_return"] is not None else None
            close_ret = float(c["return_7h"]) if c["return_7h"] is not None else None
            label = self._classify(max_ret, close_ret)
            correct = self._check(risk.verdict, label)

            # DB 저장
            self.db.upsert_verdict({
                "capture_date": capture_date,
                "code": code,
                "risk_score": risk.total,
                "verdict": risk.verdict,
                "score_volume": risk.scores.get("volume", 0),
                "score_gap": risk.scores.get("gap", 0),
                "score_early": risk.scores.get("early_move", 0),
                "score_cap": risk.scores.get("market_cap", 0),
                "score_wick": risk.scores.get("wick", 0),
                "score_volratio": risk.scores.get("vol_ratio", 0),
                "score_closepos": risk.scores.get("close_pos", 0),
                "score_bearish": risk.scores.get("bearish", 0),
                "evidence": json.dumps(risk.evidence, ensure_ascii=False),
            })
            self.db.update_verdict_actual(
                capture_date, code, max_ret, close_ret, label, correct
            )

            mark = "✅" if correct else "❌"
            print(f"  {mark} {name:10s} 위험={risk.total:3d} [{risk.verdict:7s}] "
                  f"실제={label:7s} (최고={max_ret}% 7h={close_ret}%)")
            for key, score, reason in risk.evidence:
                print(f"     └ +{score:2d}  {reason}")

    # ══════════ STEP 4: KPI 집계 ══════════

    def compute_kpi(self, capture_date: date):
        verdicts = self.db.get_verdicts(capture_date)
        if not verdicts:
            return

        total = len(verdicts)
        pass_list = [v for v in verdicts if v["verdict"] == "PASS"]
        block_list = [v for v in verdicts if v["verdict"] == "BLOCK"]
        caution_list = [v for v in verdicts if v["verdict"] == "CAUTION"]

        all_mines = [v for v in verdicts
                     if v["actual_label"] in ("LOSER", "TRAP")]

        # BLOCK 정확도: BLOCK 중 실제 지뢰 비율
        block_mines = [v for v in block_list
                       if v["actual_label"] in ("LOSER", "TRAP")]
        block_acc = (len(block_mines) / len(block_list) * 100
                     ) if block_list else None

        # PASS 안전율: PASS 중 지뢰 비율 (낮을수록 좋음)
        pass_mines = [v for v in pass_list
                      if v["actual_label"] in ("LOSER", "TRAP")]
        pass_safety = (len(pass_mines) / len(pass_list) * 100
                       ) if pass_list else None

        # PASS 승률: PASS 중 WINNER 비율
        pass_winners = [v for v in pass_list
                        if v["actual_label"] == "WINNER"]
        pass_win = (len(pass_winners) / len(pass_list) * 100
                    ) if pass_list else None

        # 지뢰 차단율: 전체 지뢰 중 BLOCK 비율
        blocked = [v for v in block_list
                   if v["actual_label"] in ("LOSER", "TRAP")]
        mine_block = (len(blocked) / len(all_mines) * 100
                      ) if all_mines else 100.0

        kpi = {
            "capture_date": capture_date,
            "total_caught": total,
            "a_pass_count": len(pass_list),
            "a_block_count": len(block_list),
            "a_caution_count": len(caution_list),
            "winner_count": sum(1 for v in verdicts
                                if v["actual_label"] == "WINNER"),
            "loser_count": sum(1 for v in verdicts
                               if v["actual_label"] == "LOSER"),
            "trap_count": sum(1 for v in verdicts
                              if v["actual_label"] == "TRAP"),
            "block_accuracy": block_acc,
            "pass_safety": pass_safety,
            "pass_winner_rate": pass_win,
            "mine_block_rate": mine_block,
            "thresholds_ver": "v1",
        }
        self.db.upsert_kpi(kpi)

        # 출력
        print(f"\n  {'═'*55}")
        print(f"  일일 KPI: {capture_date}")
        print(f"  {'═'*55}")
        print(f"  포착={total}  PASS={len(pass_list)}  "
              f"BLOCK={len(block_list)}  CAUTION={len(caution_list)}")
        print(f"  WINNER={kpi['winner_count']}  "
              f"LOSER={kpi['loser_count']}  TRAP={kpi['trap_count']}")
        print(f"  {'─'*55}")
        if block_acc is not None:
            print(f"  BLOCK 정확도  = {block_acc:5.1f}%  "
                  f"({len(block_mines)}/{len(block_list)})")
        if pass_safety is not None:
            print(f"  PASS 안전율   = {100 - pass_safety:5.1f}%  "
                  f"(지뢰 {len(pass_mines)}/{len(pass_list)})")
        if pass_win is not None:
            print(f"  PASS 승률     = {pass_win:5.1f}%  "
                  f"({len(pass_winners)}/{len(pass_list)})")
        print(f"  지뢰 차단율   = {mine_block:5.1f}%  "
              f"({len(blocked)}/{len(all_mines)})")
        print(f"  {'═'*55}")

    # ══════════ ALL-IN-ONE ══════════

    def run_full(self, raw_text: str, capture_date: date):
        print(f"\n{'#'*60}")
        print(f"  BacktestRunner: {capture_date}")
        print(f"{'#'*60}")

        self.import_clipboard(raw_text, capture_date)
        self.download_candles(capture_date)
        self.run_agent(capture_date)
        self.compute_kpi(capture_date)

    # ══════════ 재분석 (다운로드 없이) ══════════

    def reanalyze(self, capture_date: date):
        print(f"\n  ♻ 재분석: {capture_date}")
        self.run_agent(capture_date)
        self.compute_kpi(capture_date)

    def reanalyze_all(self):
        dates = self.db.get_all_caught_dates()
        print(f"\n  ♻ 전체 재분석: {len(dates)}일")
        for d in dates:
            self.reanalyze(d)

    # ══════════ 내부 유틸 ══════════

    def _classify(self, max_ret, close_ret) -> str:
        if max_ret is None:
            return "UNKNOWN"
        if max_ret >= PERFORMANCE["winner_min"]:
            return "WINNER"
        if max_ret >= PERFORMANCE["good_min"]:
            return "GOOD"
        if close_ret is not None and close_ret <= PERFORMANCE["trap_max"]:
            return "TRAP"
        if close_ret is not None and close_ret <= PERFORMANCE["loser_max"]:
            return "LOSER"
        return "NORMAL"

    def _check(self, verdict: str, label: str) -> bool:
        if verdict == "BLOCK" and label in ("LOSER", "TRAP"):
            return True
        if verdict == "PASS" and label in ("WINNER", "GOOD", "NORMAL"):
            return True
        if verdict == "BLOCK" and label == "WINNER":
            return False
        if verdict == "PASS" and label in ("LOSER", "TRAP"):
            return False
        return True
