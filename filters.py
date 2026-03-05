#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
filters.py — 횡보 필터 플러그인
  각 함수: df → numpy bool 배열 (True=횡보, False=추세)
  새 필터 추가: 함수 작성 → FILTER_REGISTRY에 등록
"""

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════
#  1. LonesomeTheBlue — Loopback 기반 박스 (TV 8,888 likes)
# ═══════════════════════════════════════════════════════════════
def filter_lonesomethblue(df, loopback=20, min_length=10):
    """
    Loopback 기간 내 최고/최저를 찾고,
    가격이 그 범위 안에 머무는 기간이 min_length 이상이면 횡보
    """
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(df)
    is_range = np.zeros(n, dtype=bool)

    range_high = np.nan
    range_low = np.nan
    count = 0

    for i in range(loopback, n):
        window_h = np.max(h[i - loopback:i + 1])
        window_l = np.min(l[i - loopback:i + 1])

        if np.isnan(range_high) or count == 0:
            range_high = window_h
            range_low = window_l
            count = 1
        else:
            # 가격이 범위 안에 있는지
            if l[i] >= range_low and h[i] <= range_high:
                count += 1
            else:
                # 범위 이탈 → 리셋
                range_high = window_h
                range_low = window_l
                count = 1

        if count >= min_length:
            is_range[i] = True

    return is_range


# ═══════════════════════════════════════════════════════════════
#  2. ADX Threshold
# ═══════════════════════════════════════════════════════════════
def filter_adx(df, adx_len=14, threshold=25):
    """ADX < threshold → 횡보"""
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(df)

    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)
    tr[0] = h[0] - l[0]

    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
        up = h[i] - h[i-1]
        dn = l[i-1] - l[i]
        plus_dm[i] = up if (up > dn and up > 0) else 0
        minus_dm[i] = dn if (dn > up and dn > 0) else 0

    # Wilder smoothing
    atr = np.zeros(n)
    s_plus = np.zeros(n)
    s_minus = np.zeros(n)

    atr[adx_len] = np.sum(tr[1:adx_len + 1])
    s_plus[adx_len] = np.sum(plus_dm[1:adx_len + 1])
    s_minus[adx_len] = np.sum(minus_dm[1:adx_len + 1])

    for i in range(adx_len + 1, n):
        atr[i] = atr[i-1] - atr[i-1] / adx_len + tr[i]
        s_plus[i] = s_plus[i-1] - s_plus[i-1] / adx_len + plus_dm[i]
        s_minus[i] = s_minus[i-1] - s_minus[i-1] / adx_len + minus_dm[i]

    di_plus = np.where(atr > 0, 100 * s_plus / atr, 0)
    di_minus = np.where(atr > 0, 100 * s_minus / atr, 0)
    di_sum = di_plus + di_minus
    dx = np.where(di_sum > 0, 100 * np.abs(di_plus - di_minus) / di_sum, 0)

    adx = np.zeros(n)
    start = adx_len * 2
    if start < n:
        adx[start] = np.mean(dx[adx_len + 1:start + 1])
        for i in range(start + 1, n):
            adx[i] = (adx[i-1] * (adx_len - 1) + dx[i]) / adx_len

    is_range = adx < threshold
    is_range[:start + 1] = False
    return is_range


# ═══════════════════════════════════════════════════════════════
#  3. Choppiness Index
# ═══════════════════════════════════════════════════════════════
def filter_choppiness(df, length=14, threshold=61.8):
    """CHOP > threshold → 횡보"""
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(df)

    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))

    chop = np.full(n, 50.0)
    for i in range(length, n):
        atr_sum = np.sum(tr[i - length + 1:i + 1])
        hh = np.max(h[i - length + 1:i + 1])
        ll = np.min(l[i - length + 1:i + 1])
        hl_range = hh - ll
        if hl_range > 0 and atr_sum > 0:
            chop[i] = 100 * np.log10(atr_sum / hl_range) / np.log10(length)

    is_range = chop > threshold
    return is_range


# ═══════════════════════════════════════════════════════════════
#  4. Bollinger Bandwidth Squeeze
# ═══════════════════════════════════════════════════════════════
def filter_bb_squeeze(df, bb_len=20, bb_std=2.0, lookback=120, squeeze_pct=25.0):
    """BW가 하위 squeeze_pct% → 횡보"""
    c = df["close"].values.astype(float)
    n = len(df)

    sma = np.full(n, np.nan)
    bw = np.full(n, np.nan)

    for i in range(bb_len - 1, n):
        window = c[i - bb_len + 1:i + 1]
        m = np.mean(window)
        s = np.std(window, ddof=0)
        sma[i] = m
        upper = m + bb_std * s
        lower = m - bb_std * s
        bw[i] = (upper - lower) / m * 100 if m > 0 else 0

    # Percentile rank
    is_range = np.zeros(n, dtype=bool)
    for i in range(lookback, n):
        window = bw[max(0, i - lookback):i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) > 0:
            pct = np.sum(valid < bw[i]) / len(valid) * 100
            if pct < squeeze_pct:
                is_range[i] = True

    return is_range


# ═══════════════════════════════════════════════════════════════
#  5. Candle Compression (Flux Charts 방식)
# ═══════════════════════════════════════════════════════════════
def filter_candle_compression(df, atr_len=14, min_candles=5):
    """캔들 몸통 < 전체 범위의 50% AND 캔들 범위 < ATR → 연속 min_candles개 이상이면 횡보"""
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    o = df["open"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(df)

    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))

    atr = np.zeros(n)
    atr[0] = tr[0]
    alpha = 2.0 / (atr_len + 1)
    for i in range(1, n):
        atr[i] = alpha * tr[i] + (1 - alpha) * atr[i-1]

    is_range = np.zeros(n, dtype=bool)
    consec = 0

    for i in range(1, n):
        body = abs(c[i] - o[i])
        candle_range = h[i] - l[i]
        is_compressed = (candle_range > 0 and body < candle_range * 0.5 and candle_range < atr[i])

        if is_compressed:
            consec += 1
        else:
            consec = 0

        if consec >= min_candles:
            is_range[i] = True

    return is_range


# ═══════════════════════════════════════════════════════════════
#  6. Volatility Compression (Zeiierman 방식)
# ═══════════════════════════════════════════════════════════════
def filter_volatility_compression(df, period=20, atr_len=14):
    """StdDev + ATR이 동시에 각각의 이동평균 미만 → 횡보"""
    c = df["close"].values.astype(float)
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    n = len(df)

    # ATR
    tr = np.zeros(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))

    atr = np.full(n, np.nan)
    for i in range(atr_len - 1, n):
        atr[i] = np.mean(tr[max(0, i - atr_len + 1):i + 1])

    # StdDev
    std = np.full(n, np.nan)
    for i in range(period - 1, n):
        std[i] = np.std(c[i - period + 1:i + 1], ddof=0)

    # 이동평균
    atr_ma = np.full(n, np.nan)
    std_ma = np.full(n, np.nan)
    for i in range(period - 1, n):
        if not np.isnan(atr[i]):
            valid_atr = atr[max(0, i - period + 1):i + 1]
            valid_atr = valid_atr[~np.isnan(valid_atr)]
            if len(valid_atr) > 0:
                atr_ma[i] = np.mean(valid_atr)
        if not np.isnan(std[i]):
            valid_std = std[max(0, i - period + 1):i + 1]
            valid_std = valid_std[~np.isnan(valid_std)]
            if len(valid_std) > 0:
                std_ma[i] = np.mean(valid_std)

    is_range = np.zeros(n, dtype=bool)
    for i in range(n):
        if (not np.isnan(atr[i]) and not np.isnan(atr_ma[i]) and
            not np.isnan(std[i]) and not np.isnan(std_ma[i])):
            if atr[i] < atr_ma[i] and std[i] < std_ma[i]:
                is_range[i] = True

    return is_range


# ═══════════════════════════════════════════════════════════════
#  필터 레지스트리 — 여기에 등록하면 콤보박스에 자동 추가
# ═══════════════════════════════════════════════════════════════
FILTER_REGISTRY = {
    "None":                 lambda df: np.zeros(len(df), dtype=bool),
    "LonesomeTheBlue":      lambda df: filter_lonesomethblue(df),
    "ADX":                  lambda df: filter_adx(df),
    "Choppiness":           lambda df: filter_choppiness(df),
    "BB_Squeeze":           lambda df: filter_bb_squeeze(df),
    "Candle_Compression":   lambda df: filter_candle_compression(df),
    "Volatility_Compression": lambda df: filter_volatility_compression(df),
}
