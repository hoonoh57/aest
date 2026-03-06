"""
strategies/base.py — 매매 전략 추상 인터페이스
  모든 전략은 이 클래스를 상속한다.
  이 파일은 절대 수정하지 않는다.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


class State(Enum):
    WAITING = "WAITING"       # 매수 대기
    HOLDING = "HOLDING"       # 보유 중
    EXITED = "EXITED"         # 청산 완료


class ExitReason(Enum):
    EMERGENCY_AEST = "EMERGENCY_AEST"    # 가격 < AEST 라인
    ST_REVERSAL = "ST_REVERSAL"          # ST 하락전환
    PROFIT_JMA = "PROFIT_JMA"            # 1%+ 수익 후 JMA 하락
    CENTRAL_STOP = "CENTRAL_STOP"        # CentralAgent 일괄 청산
    MANUAL = "MANUAL"                    # 수동 청산


@dataclass
class Signal:
    """봉 단위 신호 데이터"""
    timestamp: str = ""
    close: float = 0.0
    open_price: float = 0.0
    high: float = 0.0
    low: float = 0.0
    aest_trend: int = 0          # +1 / -1
    aest_line: float = 0.0
    st_trend: int = 0            # +1 / -1
    st_line: float = 0.0
    jma_trend: int = 0           # +1 / -1 / 0
    jma_line: float = 0.0
    atr: float = 0.0
    tick_intensity: int = 0
    tick_ma5: float = 0.0
    tick_ma20: float = 0.0
    today_open: float = 0.0      # 당일 시초가
    prev_close: float = 0.0      # 전봉 종가
    prev_jma_trend: int = 0      # 전봉 JMA trend
    prev_st_trend: int = 0       # 전봉 ST trend
    consecutive_bull: int = 0    # 연속 양봉 수
    candle_rise: float = 0.0     # 현재봉 상승률 (%)
    market: str = "KOSDAQ"       # KOSPI / KOSDAQ


@dataclass
class TradeRecord:
    """매매 기록"""
    code: str = ""
    name: str = ""
    strategy: str = ""
    buy_time: str = ""
    buy_price: float = 0.0
    sell_time: str = ""
    sell_price: float = 0.0
    quantity: int = 0
    pnl_pct: float = 0.0
    exit_reason: ExitReason = None


class BaseStrategy(ABC):
    """
    매매 전략 추상 클래스
    모든 전략은 이 인터페이스를 구현한다.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """전략 이름 (예: 'v1_standard')"""
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """전략 버전 (예: '1.0.0')"""
        pass

    @abstractmethod
    def should_buy(self, signal: Signal) -> bool:
        """매수 여부 판단"""
        pass

    @abstractmethod
    def should_sell(self, signal: Signal, entry_price: float,
                    current_pnl_pct: float) -> Optional[ExitReason]:
        """
        매도 여부 판단
        Returns: ExitReason if 매도, None if 홀딩
        """
        pass

    @abstractmethod
    def get_params(self) -> dict:
        """전략 파라미터 반환 (비교용)"""
        pass
