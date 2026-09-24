
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.dates import date2num
import matplotlib.dates as mdates
import numpy as np


def load_ohlcv_data(file_path):
   data = pd.read_csv(file_path)
   data['Timestamp'] = pd.to_datetime(data['OpenTime'])
   data.set_index('Timestamp', inplace=True)
   return data[['open', 'high', 'low', 'close', 'volume']]
   

def calculate_adx(data, period=14):
    """
    Function to calculate Average Directional Index (ADX).
    
    Parameters:
        data (DataFrame): A Pandas DataFrame with columns: 'high', 'low', 'close'.
        period (int): The period to calculate ADX (default is 14).
    
    Returns:
        DataFrame: The input DataFrame with additional columns: '+DI', '-DI', 'DX', and 'ADX'.
    """
    # Calculate True Range (TR)
    data['TR'] = np.maximum(data['high'] - data['low'], 
                            np.maximum(abs(data['high'] - data['close'].shift(1)), 
                                       abs(data['low'] - data['close'].shift(1))))

    # Calculate Directional Movement (DM)
    data['+DM'] = np.where((data['high'] - data['high'].shift(1)) > (data['low'].shift(1) - data['low']), 
                           np.maximum(data['high'] - data['high'].shift(1), 0), 0)
    data['-DM'] = np.where((data['low'].shift(1) - data['low']) > (data['high'] - data['high'].shift(1)), 
                           np.maximum(data['low'].shift(1) - data['low'], 0), 0)

    # Smooth the values using Wilder's Moving Average
    data['TR_smooth'] = data['TR'].rolling(window=period).sum()
    data['+DM_smooth'] = data['+DM'].rolling(window=period).sum()
    data['-DM_smooth'] = data['-DM'].rolling(window=period).sum()

    # Calculate Directional Indicators (+DI and -DI)
    data['+DI'] = (data['+DM_smooth'] / data['TR_smooth']) * 100
    data['-DI'] = (data['-DM_smooth'] / data['TR_smooth']) * 100

    # Calculate Directional Index (DX)
    data['DX'] = (abs(data['+DI'] - data['-DI']) / (data['+DI'] + data['-DI'])) * 100

    # Calculate ADX
    data['ADX'] = data['DX'].rolling(window=period).mean()

    # Drop intermediate columns (optional)
    data.drop(columns=['TR', '+DM', '-DM', 'TR_smooth', '+DM_smooth', '-DM_smooth', 'DX'], inplace=True, errors='ignore')
    
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

    # Plot ADX and its Average in the lower subplot
    ax2.plot(data.index, data['ADX'], color='yellow', label='ADX', linewidth=2)
    ax2.set_title("ADX and Average ADX in Percentage", fontsize=14)
    ax2.set_xlabel("Time", fontsize=12)
    ax2.set_ylabel("ADX (%)", fontsize=12)
    ax2.grid(True)
    ax2.legend(loc="upper left")

    # Formatting the x-axis
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%b, %d, %H:%M'))
    fig.autofmt_xdate()

    # Tight layout for better spacing
    plt.tight_layout()
    plt.show()
