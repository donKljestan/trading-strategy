
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

def calculate_average_volume(data, length=100):
    """
    Computes the average trading volume over the previous 'length' periods.

    Parameters:
        data (DataFrame): DataFrame with a 'volume' column.
        length (int): Period for the average (default: 100).

    Returns:
        DataFrame: DataFrame with an added 'Average Volume' column.
    """
    if 'volume' not in data.columns:
        raise ValueError("DataFrame must contain a 'volume' column.")

    data['Average Volume'] = data['volume'].rolling(window=length).mean()

    return data

def calculate_percentage_difference_volume(data):
    """
    Calculates the percentage difference between 'Average Volume' and 'volume'.

    Parameters:
        data (DataFrame): A DataFrame containing the columns 'Average Volume' and 'volume'.

    Returns:
        DataFrame: Updated DataFrame with a new column 'PctDiff_VolumeVsAvg' that contains
                   the percentage difference.
    """
    # Ensure the required columns exist
    required_columns = ['Average Volume', 'volume']
    for col in required_columns:
        if col not in data.columns:
            raise ValueError(f"DataFrame must contain the column '{col}'.")

    # Compute the percentage difference
    data['DiffVolumeVsAvg'] = (data['volume'] - data['Average Volume']) / data['Average Volume']

    return data

def scale_average_volume(data, column='Average Volume', min_range=0, max_range=1):
    """
    Scales the average trading volume to the given range.

    Parameters:
        data (DataFrame): DataFrame with the column to scale.
        column (str): Name of the column to scale (default: 'Average Volume').
        min_range (float): Minimum value of the scaling range (default: 0).
        max_range (float): Maximum value of the scaling range (default: 1).

    Returns:
        DataFrame: DataFrame with an added 'Scaled Average Volume' column.
    """
    if column not in data.columns:
        raise ValueError(f"Column '{column}' does not exist in the DataFrame.")

    # Column min and max
    min_val = data[column].min()
    max_val = data[column].max()

    # Scaling
    data['Scaled Average Volume'] = ((data[column] - min_val) / (max_val - min_val)) * (max_range - min_range) + min_range

    return data

def plot_candlesticks(data, average_window=100):
    """
    Plots the candlestick chart and Volume as vertical lines with Average Volume as a line.
    
    Parameters:
        data (DataFrame): Market data with 'open', 'high', 'low', 'close', and 'volume' columns.
        average_window (int): Number of periods to calculate the average volume (default: 100).
        
    Returns:
        None
    """
    import matplotlib.pyplot as plt
    from matplotlib.dates import date2num
    import matplotlib.dates as mdates

    # Calculate average volume
    data['Average Volume'] = data['volume'].rolling(window=average_window).mean()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True, gridspec_kw={'height_ratios': [3, 1]})

    # Plot candlesticks in the upper subplot
    candle_width = 0.7  # Width of candlesticks
    for idx, row in data.iterrows():
        color = 'green' if row['close'] >= row['open'] else 'red'
        ax1.vlines(date2num(idx), row['low'], row['high'], color='black', linewidth=1, zorder=1)
        ax1.vlines(date2num(idx), row['open'], row['close'], color=color, linewidth=candle_width, zorder=2)

    # Add candlestick chart labels and formatting
    ax1.set_title("Candlestick Chart", fontsize=14)
    ax1.set_ylabel("Price", fontsize=12)
    ax1.grid(True)

    # Plot Volume as vertical lines in the lower subplot
    for idx, row in data.iterrows():
        color = 'green' if row['close'] >= row['open'] else 'red'
        ax2.vlines(date2num(idx), 0, row['volume'], color=color, linewidth=2, zorder=2)
    
    # Plot Average Volume as a line
    ax2.plot(data.index, data['DiffVolumeVsAvg'], color='blue', linestyle='--', label=f'Average Volume ({average_window} periods)', linewidth=2)

    ax2.set_title("Volume (with Average Volume)", fontsize=14)
    ax2.set_xlabel("Time", fontsize=12)
    ax2.set_ylabel("Volume", fontsize=12)
    ax2.grid(True)
    ax2.legend(loc="upper left")

    # Formatting the x-axis
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%b, %d, %H:%M'))
    fig.autofmt_xdate()

    # Tight layout for better spacing
    plt.tight_layout()
    plt.show()





