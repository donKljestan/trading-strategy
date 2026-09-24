# Verified against ATR (%) on TradingView: identical values for identical candles

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.dates import date2num
import matplotlib.dates as mdates
import numpy as np
import pandas_ta as ta


def load_ohlcv_data(file_path):
   data = pd.read_csv(file_path)
   data['Timestamp'] = pd.to_datetime(data['OpenTime'])
   data.set_index('Timestamp', inplace=True)
   return data[['open', 'high', 'low', 'close', 'volume']]
   

def calculate_ATR_and_average(data, atr_length=14, average_window=100):
    """
    Computes ATR and the rolling average ATR over the given window.

    Parameters:
        data (DataFrame): Market data with columns 'high', 'low', 'close'.
        atr_length (int): Number of periods for the ATR (default: 14).
        average_window (int): Number of periods for the rolling ATR average (default: 100).

    Returns:
        DataFrame: DataFrame with added columns 'ATR' and 'Average ATR'.
    """
    # Ensure the required columns exist
    if not all(col in data.columns for col in ['high', 'low', 'close']):
        raise ValueError("Data must contain columns: 'high', 'low', 'close'")

    # Compute True Range
    high_prices = data['high']
    low_prices = data['low']
    close_prices = data['close']
    tr = ta.true_range(high_prices, low_prices, close_prices)

    # Scale True Range to percentage
    close_prices_shifted = close_prices.shift(1)
    scaled_tr = tr * (100 / close_prices_shifted)

    # Compute ATR
    data['ATR'] = ta.sma(scaled_tr, length=atr_length)

    # Compute the rolling average ATR
    data['Average ATR'] = data['ATR'].rolling(window=average_window).mean()

    return data


def calculate_difference(data):
    """
    Calculates the percentage difference between ATR and Average ATR.
    
    Parameters:
        data (DataFrame): Market data containing 'ATR' and 'Average ATR' columns.
        
    Returns:
        DataFrame: Updated data with a new column 'ATRDiff'.
    """
    # Ensure both columns exist
    if 'ATR' not in data.columns or 'Average ATR' not in data.columns:
        raise ValueError("DataFrame must contain 'ATR' and 'Average ATR' columns.")

    # Compute the percentage difference
    data['ATRDiff'] = (data['ATR'] - data['Average ATR']) / data['Average ATR']

    return data
    
def plot_candlesticks(data):
    """
    Plots the candlestick chart with ATR and its Average in a separate subplot below.
    
    Parameters:
        data (DataFrame): Market data with 'open', 'high', 'low', 'close', 'ATR', and 'Average ATR' columns.
        
    Returns:
        None
    """
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True, gridspec_kw={'height_ratios': [3, 1]})

    # Plot candlesticks in the upper subplot
    for idx, row in data.iterrows():
        color = 'green' if row['close'] >= row['open'] else 'red'
        ax1.vlines(date2num(idx), row['low'], row['high'], color='black', linewidth=1, zorder=1)
        ax1.vlines(date2num(idx), row['open'], row['close'], color=color, linewidth=4, zorder=2)

    ax1.set_title("Candlestick Chart", fontsize=14)
    ax1.set_ylabel("Price", fontsize=12)
    ax1.grid(True)

    # Plot ATR and its Average in the lower subplot
    ax2.plot(data.index, data['ATR'], color='yellow', label='ATR', linewidth=2)
    ax2.plot(data.index, data['Average ATR'], color='blue', linestyle='--', label='Average ATR (100 periods)', linewidth=2)
    ax2.plot(data.index, data['ATRDiff'], color='green', linestyle='--', label='Difference between ATR and Average ATR', linewidth=2)
    ax2.set_title("ATR and Average ATR in Percentage", fontsize=14)
    ax2.set_xlabel("Time", fontsize=12)
    ax2.set_ylabel("ATR (%)", fontsize=12)
    ax2.grid(True)
    ax2.legend(loc="upper left")

    # Formatting the x-axis
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%b, %d, %H:%M'))
    fig.autofmt_xdate()

    # Tight layout for better spacing
    plt.tight_layout()
    plt.show()
