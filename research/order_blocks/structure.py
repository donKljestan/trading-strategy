"""
Market-structure detection for the Smart Money Concepts research (Phase G):
Change of Character (CHoCH) and the order blocks derived from it.

Compared with the raw ``find_peaks`` swings in ``order_blocks.py``, this module
works on a smoothed price series (SMA of close) and applies a volatility filter
so that only meaningful pivots are kept. On top of the resulting HH/HL/LH/LL
structure it detects "triangles" that mark a Change of Character and turns them
into CHoCH order-block zones.

Tunable parameters (documented in ``docs/phase_G.md``):
    * ``drop_percent``  - required pullback depth inside the triangle.
    * ``rise_percent``  - required recovery before the structure is confirmed.
    * ``threshold``     - volatility floor below which pivots are discarded.
"""

import numpy as np
import pandas as pd


def load_ohlcv_data(file_path):
    """Load OHLCV data from ``file_path`` and index it by parsed OpenTime."""
    data = pd.read_csv(file_path)
    data["Timestamp"] = pd.to_datetime(data["OpenTime"])
    data.set_index("Timestamp", inplace=True)
    return data[["open", "high", "low", "close", "volume"]]


def calculate_average_volume(data, length=100):
    """Add a rolling 'Average Volume' column used by the triangle filters."""
    data["Average Volume"] = data["volume"].rolling(window=length).mean()
    return data


def detect_strict_local_maxima(data, window=3):
    """
    Flag values on the smoothed price (SMA-10) that strictly exceed their
    ``window`` predecessors and successors.

    Returns the data with a 'StrictLocalMaxima' column.
    """
    data = data.copy()
    data["SMA"] = data["close"].rolling(window=10).mean()
    data["StrictLocalMaxima"] = None

    for i in range(window, len(data) - window):
        current_value = data["SMA"].iloc[i]
        predecessors = data["SMA"].iloc[i - window:i]
        successors = data["SMA"].iloc[i + 1:i + 1 + window]
        if current_value > max(predecessors) and current_value > max(successors):
            data.loc[data.index[i], "StrictLocalMaxima"] = current_value
    return data


def detect_strict_local_minima(data, window=3):
    """
    Flag values on the smoothed price (SMA-10) that are strictly below their
    ``window`` predecessors and successors.

    Returns the data with a 'StrictLocalMinima' column.
    """
    data = data.copy()
    data["SMA"] = data["close"].rolling(window=10).mean()
    data["StrictLocalMinima"] = None

    for i in range(window, len(data) - window):
        current_value = data["SMA"].iloc[i]
        predecessors = data["SMA"].iloc[i - window:i]
        successors = data["SMA"].iloc[i + 1:i + 1 + window]
        if current_value < min(predecessors) and current_value < min(successors):
            data.loc[data.index[i], "StrictLocalMinima"] = current_value
    return data


def calculate_scaled_volatility_for_maxima(data, column="StrictLocalMaxima", threshold=0.13):
    """
    Keep only local maxima whose exponentially-scaled volatility to the previous
    maximum is above ``threshold``. Confirmed pivots are marked "H" in a new
    'LocalMaxima' column.
    """
    data["LocalMaxima"] = None
    maxima_dates = [idx for idx, row in data.iterrows() if not pd.isna(row[column])]

    for i in range(1, len(maxima_dates)):
        prev_date = maxima_dates[i - 1]
        curr_date = maxima_dates[i]
        segment = data.loc[prev_date:curr_date, "SMA"]
        if len(segment) < 2:
            continue

        absolute_changes = np.abs(np.diff(segment))
        scaling_factors = segment.shift(1).iloc[1:]
        scaled_changes = absolute_changes / scaling_factors.values
        exp_volatility = 100 * np.mean(np.exp(scaled_changes) - 1)
        if exp_volatility >= threshold:
            data.at[curr_date, "LocalMaxima"] = "H"
        else:
            data.at[prev_date, "LocalMaxima"] = None
            data.at[curr_date, "LocalMaxima"] = "H"
    return data


def calculate_scaled_volatility_for_minima(data, column="StrictLocalMinima", threshold=0.13):
    """
    Keep only local minima whose exponentially-scaled volatility to the previous
    minimum is above ``threshold``. Confirmed pivots are marked "L" in a new
    'LocalMinima' column.
    """
    data["Volatility"] = None
    data["LocalMinima"] = None
    minima_dates = [idx for idx, row in data.iterrows() if not pd.isna(row[column])]

    for i in range(1, len(minima_dates)):
        prev_date = minima_dates[i - 1]
        curr_date = minima_dates[i]
        segment = data.loc[prev_date:curr_date, "SMA"]
        if len(segment) < 2:
            continue

        absolute_changes = np.abs(np.diff(segment))
        scaling_factors = segment.shift(1).iloc[1:]
        scaled_changes = absolute_changes / scaling_factors.values
        exp_volatility = 100 * np.mean(np.exp(scaled_changes) - 1)
        data.at[curr_date, "Volatility"] = exp_volatility
        if exp_volatility >= threshold:
            data.at[curr_date, "LocalMinima"] = "L"
        else:
            data.at[prev_date, "LocalMinima"] = None
            data.at[curr_date, "LocalMinima"] = "L"
    return data


def label_swings_SMA(data):
    """
    Label the confirmed smoothed pivots as HH, HL, LH or LL based on the trend
    of the SMA. Returns the data with a 'SwingLabel' column.
    """
    data["SwingLabel"] = None
    last_swing_high, last_swing_low = None, None

    for idx, row in data.iterrows():
        if not pd.isna(row["LocalMaxima"]):
            if last_swing_high is not None and row["SMA"] > last_swing_high:
                data.loc[idx, "SwingLabel"] = "HH"
            else:
                data.loc[idx, "SwingLabel"] = "LH"
            last_swing_high = row["SMA"]

    for idx, row in data.iterrows():
        if not pd.isna(row["LocalMinima"]):
            if last_swing_low is not None and row["SMA"] < last_swing_low:
                data.loc[idx, "SwingLabel"] = "LL"
            else:
                data.loc[idx, "SwingLabel"] = "HL"
            last_swing_low = row["SMA"]
    return data


def found_triangle_maxima(data, drop_percent=4, rise_percent=2):
    """
    Detect a bullish Change of Character.

    Scans for a triangle formed between two pivots (LH/HH) and a third point
    that closes back above the middle pivot. A valid triangle requires a
    pullback of at least ``drop_percent`` from the start pivot, an intermediate
    pullback of at least ``drop_percent - 1`` and a recovery of at least
    ``rise_percent`` on above-average volume. Confirmed CHoCH order blocks are
    stored in 'CHoCHOrderBlockHighBullish'/'CHoCHOrderBlockLowBullish'.
    """
    first_pivot_found = False
    start_idx, middle_idx = None, None
    data["TriangleBullish"] = None
    data["CHoCHOrderBlockHighBullish"] = None
    data["CHoCHOrderBlockLowBullish"] = None
    min_price = 1_000_000
    min_index = 0

    for idx, row in data.iterrows():
        if not first_pivot_found and row["SwingLabel"] in ["LH", "HH"]:
            start_idx = idx
            first_pivot_found = True
            min_price = 1_000_000
            continue

        if row["low"] < min_price:
            min_price = row["low"]
            min_index = idx

        if first_pivot_found and middle_idx is None and row["SwingLabel"] == "LH":
            middle_idx = idx
            continue

        if first_pivot_found and middle_idx is not None:
            start_price = data.loc[start_idx, "high"]
            middle_price = data.loc[middle_idx, "high"]
            current_price = row["close"]

            if row["SwingLabel"] in ["HH", "LH"] and idx != middle_idx:
                if row["SwingLabel"] == "HH":
                    start_idx = idx
                    middle_idx = None
                    min_price = 1_000_000
                else:
                    start_idx = middle_idx
                    middle_idx = idx
                    min_price = data.loc[start_idx:middle_idx, "low"].min()
                    min_index = data.loc[start_idx:middle_idx, "low"].idxmin()
                continue

            drop = ((start_price - min_price) / start_price) * 100
            drop_middle = ((start_price - middle_price) / start_price) * 100
            rise = ((current_price - min_price) / current_price) * 100

            if (drop >= drop_percent and drop_middle >= (drop_percent - 1)
                    and rise >= rise_percent and row["close"] > middle_price):
                average_volume = data.loc[min_index:idx, "volume"].mean()
                if average_volume > 1.1 * row["Average Volume"]:
                    data.loc[idx, "TriangleBullish"] = "T"
                    start_idx = middle_idx
                    middle_idx = None
                    data.loc[idx, "CHoCHOrderBlockHighBullish"] = row["close"]
                    data.loc[idx, "CHoCHOrderBlockLowBullish"] = min_price
                    min_price = data.loc[start_idx:idx, "low"].min()
    return data


def found_triangle_minima(data, drop_percent=4, rise_percent=2):
    """
    Detect a bearish Change of Character (mirror image of
    ``found_triangle_maxima``). Confirmed CHoCH order blocks are stored in
    'CHoCHOrderBlockHighBearish'/'CHoCHOrderBlockLowBearish'.
    """
    first_pivot_found = False
    start_idx, middle_idx = None, None
    data["TriangleBearish"] = None
    data["CHoCHOrderBlockHighBearish"] = None
    data["CHoCHOrderBlockLowBearish"] = None
    max_price = 0
    max_index = 0

    for idx, row in data.iterrows():
        if not first_pivot_found and row["SwingLabel"] in ["LL", "HL"]:
            start_idx = idx
            first_pivot_found = True
            max_price = 0
            continue

        if row["high"] > max_price:
            max_price = row["high"]
            max_index = idx

        if first_pivot_found and middle_idx is None and row["SwingLabel"] == "HL":
            middle_idx = idx
            continue

        if first_pivot_found and middle_idx is not None:
            start_price = data.loc[start_idx, "low"]
            middle_price = data.loc[middle_idx, "low"]
            current_price = row["close"]

            if row["SwingLabel"] in ["LL", "HL"] and idx != middle_idx:
                if row["SwingLabel"] == "LL":
                    start_idx = idx
                    middle_idx = None
                    max_price = 0
                else:
                    start_idx = middle_idx
                    middle_idx = idx
                    max_price = data.loc[start_idx:middle_idx, "high"].max()
                    max_index = data.loc[start_idx:middle_idx, "high"].idxmax()
                continue

            drop = ((max_price - start_price) / max_price) * 100
            drop_middle = ((middle_price - start_price) / middle_price) * 100
            rise = ((max_price - current_price) / max_price) * 100

            if (drop >= drop_percent and drop_middle >= (drop_percent - 1)
                    and rise >= rise_percent and row["close"] < middle_price):
                average_volume = data.loc[max_index:idx, "volume"].mean()
                if average_volume > 1.1 * row["Average Volume"]:
                    data.loc[idx, "TriangleBearish"] = "T"
                    start_idx = middle_idx
                    middle_idx = None
                    data.loc[idx, "CHoCHOrderBlockHighBearish"] = max_price
                    data.loc[idx, "CHoCHOrderBlockLowBearish"] = row["close"]
                    max_price = data.loc[start_idx:idx, "high"].max()
    return data


def label_CHoCH_order_blocks(data, max_hold_days=200):
    """
    Turn detected CHoCH pivots into active order-block zones.

    A bullish CHoCH order block stays active (``isCHoCHOrderBlock`` = 1) from its
    formation until price trades back into the block low, and a bearish one
    (``isCHoCHOrderBlock`` = -1) until price trades back into the block high, or
    until ``max_hold_days`` elapse.
    """
    data = data.reset_index()
    data["endIdx"] = None
    data["isCHoCHOrderBlock"] = 0

    for idx, row in data.iterrows():
        if not pd.isna(row["CHoCHOrderBlockHighBullish"]) and not pd.isna(row["CHoCHOrderBlockLowBullish"]):
            order_block_price = row["CHoCHOrderBlockLowBullish"]
            start_idx = idx
            end_idx = None
            row_time = pd.to_datetime(data.loc[idx, "Timestamp"])
            for future_idx, future_row in data.loc[(idx + 1):].iterrows():
                if (future_row["open"] <= order_block_price <= future_row["close"]
                        or future_row["close"] <= order_block_price <= future_row["open"]):
                    end_idx = future_idx
                    data.loc[idx, "endIdx"] = future_row["Timestamp"]
                    break
                future_row_time = pd.to_datetime(future_row["Timestamp"])
                if (future_row_time - row_time).days > max_hold_days or future_idx == data.index[-1]:
                    end_idx = future_idx
                    data.loc[idx, "endIdx"] = future_row["Timestamp"]
                    break
            if end_idx:
                data.loc[start_idx:end_idx, "isCHoCHOrderBlock"] = 1

        if not pd.isna(row["CHoCHOrderBlockHighBearish"]) and not pd.isna(row["CHoCHOrderBlockLowBearish"]):
            order_block_price = row["CHoCHOrderBlockHighBearish"]
            start_idx = idx
            end_idx = None
            row_time = pd.to_datetime(data.loc[idx, "Timestamp"])
            for future_idx, future_row in data.loc[(idx + 1):].iterrows():
                if (future_row["open"] <= order_block_price <= future_row["close"]
                        or future_row["close"] <= order_block_price <= future_row["open"]):
                    end_idx = future_idx
                    data.loc[idx, "endIdx"] = future_row["Timestamp"]
                    break
                future_row_time = pd.to_datetime(future_row["Timestamp"])
                if (future_row_time - row_time).days > max_hold_days or future_idx == data.index[-1]:
                    end_idx = future_idx
                    data.loc[idx, "endIdx"] = future_row["Timestamp"]
                    break
            if end_idx:
                data.loc[start_idx:end_idx, "isCHoCHOrderBlock"] = -1

    data.set_index("Timestamp", inplace=True)
    return data
