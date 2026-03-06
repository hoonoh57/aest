"""
layer2/portfolio.py — 포지션 및 포트폴리오 손익 추적
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from strategies.base import TradeRecord, ExitReason


@dataclass
class Position:
    """개별 종목 포지션"""
    code: str = ""
    name: str = ""
    buy_price: float = 0.0
    quantity: int = 0
    buy_time: str = ""
    current_price: float = 0.0

    @property
    def pnl_pct(self) -> float:
        if self.buy_price <= 0:
            return 0.0
        return (self.current_price - self.buy_price) / self.buy_price * 100

    @property
    def pnl_amount(self) -> float:
        return (self.current_price - self.buy_price) * self.quantity


@dataclass
class PortfolioSnapshot:
    """포트폴리오 스냅샷"""
    timestamp: str = ""
    total_invested: float = 0.0
    total_value: float = 0.0
    total_pnl_pct: float = 0.0
    position_count: int = 0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0


class Portfolio:
    """포트폴리오 관리"""

    def __init__(self, initial_capital: float = 100_000_000):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.trades: List[TradeRecord] = []
        self.realized_pnl: float = 0.0

    def buy(self, code: str, name: str, price: float,
            amount: float, timestamp: str) -> Optional[Position]:
        """매수 (금액 기준)"""
        if price <= 0 or amount <= 0:
            return None
        qty = int(amount / price)
        if qty <= 0:
            return None
        cost = price * qty
        if cost > self.cash:
            qty = int(self.cash / price)
            if qty <= 0:
                return None
            cost = price * qty
        self.cash -= cost
        pos = Position(
            code=code, name=name,
            buy_price=price, quantity=qty,
            buy_time=timestamp, current_price=price
        )
        self.positions[code] = pos
        return pos

    def sell(self, code: str, price: float, timestamp: str,
             reason: ExitReason, strategy: str = "") -> Optional[TradeRecord]:
        """전량 매도"""
        pos = self.positions.get(code)
        if not pos:
            return None
        pnl_pct = (price - pos.buy_price) / pos.buy_price * 100
        proceeds = price * pos.quantity
        self.cash += proceeds
        self.realized_pnl += proceeds - (pos.buy_price * pos.quantity)
        trade = TradeRecord(
            code=code, name=pos.name,
            strategy=strategy,
            buy_time=pos.buy_time, buy_price=pos.buy_price,
            sell_time=timestamp, sell_price=price,
            quantity=pos.quantity,
            pnl_pct=round(pnl_pct, 2),
            exit_reason=reason
        )
        self.trades.append(trade)
        del self.positions[code]
        return trade

    def update_price(self, code: str, price: float):
        """현재가 갱신"""
        if code in self.positions:
            self.positions[code].current_price = price

    def snapshot(self, timestamp: str = "") -> PortfolioSnapshot:
        """현재 스냅샷"""
        unrealized = sum(p.pnl_amount for p in self.positions.values())
        total_invested = sum(
            p.buy_price * p.quantity for p in self.positions.values()
        )
        total_value = self.cash + sum(
            p.current_price * p.quantity for p in self.positions.values()
        )
        total_pnl_pct = ((total_value - self.initial_capital)
                         / self.initial_capital * 100)
        return PortfolioSnapshot(
            timestamp=timestamp,
            total_invested=total_invested,
            total_value=total_value,
            total_pnl_pct=round(total_pnl_pct, 2),
            position_count=len(self.positions),
            realized_pnl=round(self.realized_pnl, 0),
            unrealized_pnl=round(unrealized, 0),
        )
