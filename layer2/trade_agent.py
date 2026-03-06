"""
layer2/trade_agent.py — 종목별 매매 실행기
  전략 객체를 주입받아 매수/매도 판단을 수행한다.
"""

from strategies.base import (BaseStrategy, Signal, State,
                              ExitReason, TradeRecord)
from layer2.portfolio import Portfolio


class TradeAgent:
    """
    종목 1개를 담당하는 매매 에이전트.
    전략(BaseStrategy)을 주입받아 판단한다.
    """

    def __init__(self, code: str, name: str,
                 strategy: BaseStrategy,
                 portfolio: Portfolio,
                 buy_amount: float = 5_000_000):
        self.code = code
        self.name = name
        self.strategy = strategy
        self.portfolio = portfolio
        self.buy_amount = buy_amount

        self.state = State.WAITING
        self.entry_price = 0.0
        self.blocked_by_central = False

    def on_bar(self, signal: Signal) -> dict:
        """
        봉 완성 시 호출. 매매 판단 수행.
        Returns: {"action": "BUY"/"SELL"/"HOLD", ...}
        """
        result = {"action": "HOLD", "code": self.code,
                  "name": self.name, "signal": signal}

        # 현재가 갱신
        self.portfolio.update_price(self.code, signal.close)

        # ── CentralAgent 차단 ──
        if self.blocked_by_central:
            if self.state == State.HOLDING:
                trade = self.portfolio.sell(
                    self.code, signal.close, signal.timestamp,
                    ExitReason.CENTRAL_STOP, self.strategy.name
                )
                self.state = State.EXITED
                result["action"] = "SELL"
                result["reason"] = ExitReason.CENTRAL_STOP
                result["trade"] = trade
            return result

        # ── WAITING → 매수 판단 ──
        if self.state == State.WAITING:
            if self.strategy.should_buy(signal):
                pos = self.portfolio.buy(
                    self.code, self.name, signal.close,
                    self.buy_amount, signal.timestamp
                )
                if pos:
                    self.state = State.HOLDING
                    self.entry_price = signal.close
                    result["action"] = "BUY"
                    result["price"] = signal.close
            return result

        # ── HOLDING → 매도 판단 ──
        if self.state == State.HOLDING:
            pnl_pct = ((signal.close - self.entry_price)
                       / self.entry_price * 100)
            exit_reason = self.strategy.should_sell(
                signal, self.entry_price, pnl_pct
            )
            if exit_reason:
                trade = self.portfolio.sell(
                    self.code, signal.close, signal.timestamp,
                    exit_reason, self.strategy.name
                )
                self.state = State.WAITING  # 재진입 가능
                self.entry_price = 0.0
                result["action"] = "SELL"
                result["reason"] = exit_reason
                result["trade"] = trade
            return result

        return result
