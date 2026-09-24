# Verified against RSI and SMA on TradingView: identical values at identical points in time

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
   

def calculate_RSI(data, length=14):
    """
    Adds an 'RSI' column to the DataFrame based on the 'close' price.

    Parameters:
        data (DataFrame): DataFrame with a 'close' column.
        length (int): Period for the RSI.

    Returns:
        DataFrame: DataFrame with an added 'RSI' column.
    """
    if 'close' not in data.columns:
        raise ValueError("DataFrame must contain a 'close' column.")

    data['RSI'] = ta.rsi(data['close'], length=length)
    return data
    

def calculate_SMA(data, length=14):
    """
    Adds an 'SMA' column to the DataFrame based on the 'RSI' column.

    Parameters:
        data (DataFrame): DataFrame with an 'RSI' column.
        length (int): Period for the SMA.

    Returns:
        DataFrame: DataFrame with an added 'SMA' column.
    """
    if 'RSI' not in data.columns:
        raise ValueError("DataFrame must contain an 'RSI' column.")

    data['SMA'] = ta.sma(data['RSI'], length=length)
    return data

def plot_candlesticks(data):
    """
    Plots candlestick chart with RSI and SMA on a separate subplot below.
    
    Parameters:
        data (DataFrame): Market data with 'open', 'high', 'low', 'close', 'RSI', and 'SMA' columns.
        
    Returns:
        None
    """
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True, gridspec_kw={'height_ratios': [3, 1]})

    # Plot candlesticks in the upper subplot
    for idx, row in data.iterrows():
        color = 'green' if row['close'] >= row['open'] else 'red'
        ax1.vlines(date2num(idx), row['low'], row['high'], color='black', linewidth=1, zorder=1)
        ax1.vlines(date2num(idx), row['open'], row['close'], color=color, linewidth=4, zorder=2)

    # Add candlestick chart labels and formatting
    ax1.set_title("Candlestick Chart", fontsize=14)
    ax1.set_ylabel("Price", fontsize=12)
    ax1.grid(True)

    # Plot RSI and SMA in the lower subplot
    ax2.plot(data.index, data['RSI'], label='RSI', color='blue', linewidth=2)
    ax2.plot(data.index, data['SMA'], label='SMA on RSI', color='orange', linewidth=2, linestyle='--')
    ax2.set_title("RSI and SMA", fontsize=14)
    ax2.set_xlabel("Time", fontsize=12)
    ax2.set_ylabel("Value", fontsize=12)
    ax2.axhline(70, color='red', linestyle='--', linewidth=1, label='Overbought (70)')
    ax2.axhline(30, color='green', linestyle='--', linewidth=1, label='Oversold (30)')
    ax2.grid(True)
    ax2.legend(loc="upper left")

    # Formatting the x-axis
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%b, %d, %H:%M'))
    fig.autofmt_xdate()

    # Tight layout for better spacing
    plt.tight_layout()
    plt.show()
