"""Downloads historical 15-minute OHLCV data for a crypto symbol from Binance into a .csv file."""

import time
import requests
from datetime import datetime, timedelta
import pandas as pd
import os


def get_previous_candles(symbol, interval="15m", days=3000, days_back=3000):

    limit = days * 96  # 96 candles per day
    start_time = int((datetime.now() - timedelta(days=days_back)).timestamp() * 1000)
    print(f"Start time: {pd.to_datetime(start_time, unit='ms')}")
    all_candles = []
    while True:
        url = "https://api.binance.com/api/v3/klines"
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': limit,
            'startTime': start_time
        }
        
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            data = response.json()
        
        if not data:
            break
        
        all_candles.extend(data)
        start_time = data[-1][0] + 1
        time.sleep(0.5)
        if len(all_candles) >= days * 96:  # stop once we have enough candles
            break
    open_times = [kline[0] for kline in all_candles]
    open_prices = [float(kline[1]) for kline in all_candles]
    high_prices = [float(kline[2]) for kline in all_candles]
    low_prices = [float(kline[3]) for kline in all_candles]
    close_prices = [float(kline[4]) for kline in all_candles]
    volumes = [float(kline[5]) for kline in all_candles]
    close_time = [float(kline[6]) for kline in all_candles]
    obimTrgovanja = [float(kline[7]) for kline in all_candles]
    brojTransakcija = [int(kline[8]) for kline in all_candles]
    kolicinaKupljenaOdTakersa = [float(kline[9]) for kline in all_candles]
    return open_times, open_prices, high_prices, low_prices, close_prices, volumes, close_time, obimTrgovanja, brojTransakcija, kolicinaKupljenaOdTakersa
    
def write_data_in_file(symbol):
    
    file_name = symbol + "_15minutni.csv"
    file_path = os.path.join(os.getcwd(), "prices", symbol, file_name)
    if not os.path.exists(file_path):    
        openTimes, openPrices, highPrices, lowPrices, closePrices, volumes, close_time, obimTrgovanja, brojTransakcija, kolicinaKupljenaOdTakersa = get_previous_candles(symbol=symbol)
        with open(file_path, "w") as file:
            num_of_candles = len(highPrices)
            file.write("OpenTime,CloseTime,open,high,low,close,volume,ObimTrgovanja,BrojTransakcija,KolicinaKupljenaOdTakersa \n")
            for i in range(num_of_candles - 1):  # -1: skip the current (unclosed) candle
                vreme_izvrsavanja = int((pd.to_datetime(openTimes[i], unit='ms') + timedelta(hours=1)).timestamp() * 1000)
                vreme_zavrsavanja = int((pd.to_datetime(close_time[i], unit='ms') + timedelta(hours=1)).timestamp() * 1000)
                file.write(f"{pd.to_datetime(vreme_izvrsavanja, unit='ms')},{pd.to_datetime(vreme_zavrsavanja, unit='ms')},{openPrices[i]},{highPrices[i]},{lowPrices[i]},{closePrices[i]},{volumes[i]},{obimTrgovanja[i]},{brojTransakcija[i]},{kolicinaKupljenaOdTakersa[i]}\n")
            
        return file_path
    return None