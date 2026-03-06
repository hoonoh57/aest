"""
layer2/central_agent.py — 포트폴리오 총괄 관리
"""

from typing import Dict, List
from layer2.trade_agent import TradeAgent
from layer2.portfolio import Portfolio, PortfolioSnapshot
from layer2.signal_engine import SignalEngine
from strategies.base import BaseStrategy


class CentralAgent:
    """
    모든 TradeAgent를 관리하고
    포트폴리오 수준 의사결정을 수행한다.
    """

    def __init__(self, strategy: BaseStrategy,
                 initial_capital: float = 100_000_000,
                 buy_amount_per_stock: float = 5_000_000,
                 daily_target: float = 2.0,
                 trailing_step: float = 0.5,
                 emergency_stop: float = -3.0):
        self.strategy = strategy
        self.portfolio = Portfolio(initial_capital)
        self.buy_amount = buy_amount_per_stock
        self.daily_target = daily_target
        self.trailing_step = trailing_step
        self.emergency_stop = emergency_stop

        self.agents: Dict[str, TradeAgent] = {}
        self.signal_engine: SignalEngine = None

        # trailing stop 상태
        self._trailing_active = False
        self._trailing_high = 0.0
        self._halted = False

        # 이력
        self.snapshots: List[PortfolioSnapshot] = []

    def set_signal_engine(self, engine: SignalEngine):
        self.signal_engine = engine

    def add_stock(self, code: str, name: str,
                  market: str = "KOSDAQ"):
        """감시 종목 추가"""
        agent = TradeAgent(
            code=code, name=name,
            strategy=self.strategy,
            portfolio=self.portfolio,
            buy_amount=self.buy_amount
        )
        self.agents[code] = agent

    def on_bar_all(self, timestamp: str = ""):
        """
        모든 종목의 봉 완성 시 호출.
        1) 각 TradeAgent에 Signal 전달
        2) 포트폴리오 손익 집계
        3) 총괄 의사결정
        """
        results = []

        # 1) 각 종목 매매 판단
        for code, agent in self.agents.items():
            try:
                signal = self.signal_engine.get_signal(code)
                result = agent.on_bar(signal)
                results.append(result)
            except Exception as e:
                print(f"  ⚠ {code} 신호 오류: {e}")

        # 2) 포트폴리오 스냅샷
        snap = self.portfolio.snapshot(timestamp)
        self.snapshots.append(snap)

        # 3) 총괄 의사결정
        self._check_portfolio(snap)

        return results, snap

    def _check_portfolio(self, snap: PortfolioSnapshot):
        """총괄 손익 기반 의사결정"""

        # 비상 정지: 총괄 손실 한도
        if snap.total_pnl_pct <= self.emergency_stop:
            self._halt_all("총괄손실한도")
            return

        # trailing stop 활성화
        if snap.total_pnl_pct >= self.daily_target:
            self._trailing_active = True

        if self._trailing_active:
            if snap.total_pnl_pct > self._trailing_high:
                self._trailing_high = snap.total_pnl_pct
            if snap.total_pnl_pct < self._trailing_high - self.trailing_step:
                self._halt_all("트레일링스탑")

    def _halt_all(self, reason: str):
        """전종목 일괄 청산 + 신규 매수 중단"""
        if self._halted:
            return
        self._halted = True
        print(f"\n  🛑 CentralAgent: {reason}")
        print(f"     총괄수익률 고점={self._trailing_high:.2f}%")
        for agent in self.agents.values():
            agent.blocked_by_central = True

    def resume(self):
        """신규 매수 재개"""
        self._halted = False
        for agent in self.agents.values():
            agent.blocked_by_central = False

    def report(self) -> dict:
        """일일 리포트"""
        trades = self.portfolio.trades
        snap = self.portfolio.snapshot()

        winners = [t for t in trades if t.pnl_pct > 0]
        losers = [t for t in trades if t.pnl_pct <= 0]
        avg_win = (sum(t.pnl_pct for t in winners) / len(winners)
                   ) if winners else 0
        avg_loss = (sum(t.pnl_pct for t in losers) / len(losers)
                    ) if losers else 0

        return {
            "strategy": self.strategy.name,
            "version": self.strategy.version,
            "total_trades": len(trades),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": round(len(winners) / max(len(trades), 1) * 100, 1),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "total_pnl_pct": snap.total_pnl_pct,
            "realized_pnl": snap.realized_pnl,
            "max_trailing_high": round(self._trailing_high, 2),
            "halted": self._halted,
            "params": self.strategy.get_params(),
        }
