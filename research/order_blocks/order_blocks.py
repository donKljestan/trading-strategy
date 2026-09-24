"""
Order Block detection for the Smart Money Concepts (SMC) research phase.

This module bundles the price-action building blocks used during Phase G of the
project:

1. Swing high/low detection via ``scipy.signal.find_peaks``.
2. Swing labelling (HH / HL / LH / LL) to describe market structure.
3. Fair Value Gap (FVG) measurement, expressed as a percentage of the candle
   body.
4. Order-block zone detection with a bounded validity window.

An "order block" is the candle that precedes a strong directional move. Here a
bullish order block is flagged when a candle shows a significant Fair Value Gap;
the zone stays active until price trades back into the block low or a maximum
holding window elapses.
"""

import numpy as np
import pandas as pd
from scipy.signal import find_peaks


def load_ohlcv_data(file_path):
    """Load OHLCV data from ``file_path`` and index it by parsed OpenTime."""
    data = pd.read_csv(file_path)
    data["Timestamp"] = pd.to_datetime(data["OpenTime"])
    data.set_index("Timestamp", inplace=True)
    return data[["open", "high", "low", "close", "volume"]]


def detect_swing_highs_and_lows(data, window=50):
    """
    Identify swing highs/lows as local extrema separated by at least ``window``
    bars.

    Parameters:
        data (DataFrame): Market data with 'high' and 'low' columns.
        window (int): Minimum bar distance between two detected extrema.

    Returns:
        DataFrame: Data with 'swingHigh' and 'swingLow' columns.
    """
    swing_high_indices = find_peaks(data["high"], distance=window)[0]
    data["swingHigh"] = np.nan
    data.loc[data.index[swing_high_indices], "swingHigh"] = data["high"].iloc[swing_high_indices]

    swing_low_indices = find_peaks(-data["low"], distance=window)[0]
    data["swingLow"] = np.nan
    data.loc[data.index[swing_low_indices], "swingLow"] = data["low"].iloc[swing_low_indices]
    return data


def label_swings(data):
    """
    Label detected swings as HH, HL, LH or LL relative to the previous swing of
    the same type. This encodes the trend structure used by the SMC rules.

    Parameters:
        data (DataFrame): Market data with 'swingHigh' and 'swingLow'.

    Returns:
        DataFrame: Data with a 'SwingLabel' column.
    """
    data["SwingLabel"] = np.nan
    last_swing_high, last_swing_low = None, None

    for idx, row in data.iterrows():
        if not pd.isna(row["swingHigh"]):
            if last_swing_high is not None and row["swingHigh"] > last_swing_high:
                data.loc[idx, "SwingLabel"] = "HH"
            else:
                data.loc[idx, "SwingLabel"] = "LH"
            last_swing_high = row["swingHigh"]

        if not pd.isna(row["swingLow"]):
            if last_swing_low is not None and row["swingLow"] < last_swing_low:
                data.loc[idx, "SwingLabel"] = "LL"
            else:
                data.loc[idx, "SwingLabel"] = "HL"
            last_swing_low = row["swingLow"]
    return data


def detect_fvg(data):
    """
    Measure the Fair Value Gap for every bar as a percentage of the candle body.

    A bullish FVG exists when the previous high and the next low do not overlap
    the current body; the bearish case is symmetric. The gap is normalised by
    the body size so that the value is comparable across price levels.

    Parameters:
        data (DataFrame): OHLC data with 'open', 'high', 'low', 'close'.

    Returns:
        DataFrame: Data with an added 'FVG' column (percentage).
    """
    required_columns = {"open", "high", "low", "close"}
    if not required_columns.issubset(data.columns):
        raise ValueError(f"DataFrame must contain the columns: {required_columns}")

    data["FVG"] = 0.0
    data = data.reset_index()

    for i in range(1, len(data) - 1):
        left_high = data.loc[i - 1, "high"]
        left_low = data.loc[i - 1, "low"]
        current_open = data.loc[i, "open"]
        current_close = data.loc[i, "close"]
        right_high = data.loc[i + 1, "high"]
        right_low = data.loc[i + 1, "low"]

        if current_close > current_open:  # bullish body
            top_of_body = max(current_open, current_close)
            bottom_of_body = min(current_open, current_close)
            if right_low > bottom_of_body and left_high < top_of_body:
                gap = min(right_low - bottom_of_body, top_of_body - left_high)
                body_size = top_of_body - bottom_of_body
                data.loc[i, "FVG"] = (gap / body_size) * 100
        elif current_close < current_open:  # bearish body
            top_of_body = max(current_open, current_close)
            bottom_of_body = min(current_open, current_close)
            if right_high < top_of_body and left_low > bottom_of_body:
                gap = min(top_of_body - right_high, left_low - bottom_of_body)
                body_size = top_of_body - bottom_of_body
                data.loc[i, "FVG"] = (gap / body_size) * 100

    data.set_index("Timestamp", inplace=True)
    return data


def detect_order_blocks_with_zone(data, fvg_threshold=50, max_hold_days=10):
    """
    Flag bullish order blocks and mark how long each zone stays active.

    A bar becomes an order block when its Fair Value Gap exceeds
    ``fvg_threshold`` percent. The zone (``isOrderBlock`` = 1) then remains
    active until price trades back into the block low or ``max_hold_days``
    elapse, whichever happens first.

    Note: a volume/gap variant was also explored during research (the last
    opposite-coloured candle before a strong move, confirmed by >2x average
    volume and a significant price gap). The FVG trigger implemented below is
    the version that was carried into backtesting.

    Parameters:
        data (DataFrame): Data with 'FVG', OHLC and a Timestamp index.
        fvg_threshold (float): Minimum FVG (%) required to open an order block.
        max_hold_days (int): Maximum lifetime of an active order-block zone.

    Returns:
        DataFrame: Data with 'OrderBlockHigh', 'OrderBlockLow' and
        'isOrderBlock' columns.
    """
    data = data.reset_index()
    data["OrderBlockHigh"] = np.nan
    data["OrderBlockLow"] = np.nan
    data["isOrderBlock"] = 0

    for idx, row in data.iterrows():
        if row["FVG"] > fvg_threshold:
            data.loc[idx, "OrderBlockHigh"] = row["high"]
            data.loc[idx, "OrderBlockLow"] = row["low"]

            order_block_price = row["low"]
            start_idx = idx
            end_idx = None
            row_time = pd.to_datetime(data.loc[idx, "Timestamp"])
            for future_idx, future_row in data.loc[idx:].iterrows():
                future_row_time = pd.to_datetime(future_row["Timestamp"])
                if (future_row_time - row_time).days > max_hold_days:
                    end_idx = future_idx
                    break
                if (future_row["open"] <= order_block_price <= future_row["close"]
                        or future_row["close"] <= order_block_price <= future_row["open"]):
                    end_idx = future_idx
                    break
            if end_idx:
                data.loc[start_idx:end_idx, "isOrderBlock"] = 1

    data.set_index("Timestamp", inplace=True)
    return data
