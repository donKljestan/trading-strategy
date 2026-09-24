"""
Parameter-sweep backtester for the pre-order-blocks BTCUSDT strategy (15-minute candles).

Strategy summary:
  - Momentum: RSI, plus an SMA computed on the RSI series.
  - Volatility filter: ATR scaled to % of price, gated to an [ATR_LOW, ATR_HIGH] band.
  - Volume confirmation: current volume above VOLUME_FACTOR * recent average volume.
  - Risk sizing: Stop Loss and Take Profit are derived from ATR through exponential
    functions controlled by two coefficients, Ks (stop-loss scaling) and Kt
    (take-profit scaling). See get_stop_loss_function / get_take_profit_function.

main() runs the Phase B experiment: it tunes the risk coefficients (Ks, Kt) *separately inside
each ATR band* (0.25-0.30, 0.30-0.40, 0.40-0.50, 0.50-0.99) and records the best profit per
band to profit_per_atr_band.csv. Each band can be made to look profitable in isolation, yet the
combined out-of-sample run is not the sum of those profits -- the overfitting trap documented in
docs/phase_B.md.

Input data: prices.txt, one 15-minute candle per line, comma separated:
    open_time, close_time, open, high, low, close, volume, ...
"""

import logging
import threading
from collections import deque
from datetime import datetime, timedelta
from statistics import mean

import numpy as np
import pandas as pd
import pandas_ta as ta


# --- Logging -------------------------------------------------------------
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

info_handler = logging.FileHandler('backtesting_info.log')
info_handler.setLevel(logging.INFO)

error_handler = logging.FileHandler('backtesting_error.log')
error_handler.setLevel(logging.ERROR)

formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s')
info_handler.setFormatter(formatter)
error_handler.setFormatter(formatter)


class MaxLevelFilter(logging.Filter):
    """Keeps the info handler from also recording ERROR-level records."""

    def __init__(self, level):
        self.max_level = level

    def filter(self, record):
        return record.levelno <= self.max_level


info_handler.addFilter(MaxLevelFilter(logging.WARNING))
logger.addHandler(info_handler)
logger.addHandler(error_handler)


# --- Strategy parameters (assigned in main, read in backtesting) ---------
RSI_SELL_THRESHOLD = 40
RSI_BUY_THRESHOLD = 60
SMA_SELL_THRESHOLD = 55
SMA_BUY_THRESHOLD = 45
ATR_THRESHOLD = 0.25       # ATR_LOW: lower bound of the volatility band
ATR_THRESHOLD1 = 1.0       # ATR_HIGH: upper bound of the volatility band
VOLUME_FACTOR = 1.5

# --- Shared state --------------------------------------------------------
calculated_profit = 0      # accumulated across Order threads
quantity = 0.002           # position size (BTC) used in the profit calculation
lock = threading.Lock()
price_lines = []           # raw lines loaded from prices.txt


def read_lines_from_file(file_name="prices.txt"):
    global price_lines
    with open(file_name, "r") as file:
        price_lines = file.readlines()


def days_from_now(date):
    return (datetime.now() - date).days


def get_previous_candles(days=30, days_back=30):
    """Return the candles from prices.txt inside the [days_back, days_back-days] window."""
    global price_lines
    start_time = int((datetime.now() - timedelta(days=days_back)).timestamp() * 1000)
    end_time = int((datetime.now() - timedelta(days=(days_back - days))).timestamp() * 1000)
    open_times, close_times = [], []
    open_prices, high_prices, low_prices, close_prices, volumes = [], [], [], [], []
    for line in price_lines:
        parameters = line.split(",")
        open_dt = datetime.strptime(parameters[0], '%Y-%m-%d %H:%M:%S')
        open_ts = int(open_dt.timestamp() * 1000)
        if start_time < open_ts < end_time:
            open_times.append(open_ts)
            close_dt = datetime.strptime(parameters[1], '%Y-%m-%d %H:%M:%S.%f')
            close_times.append(int(close_dt.timestamp() * 1000))
            open_prices.append(float(parameters[2]))
            high_prices.append(float(parameters[3]))
            low_prices.append(float(parameters[4]))
            close_prices.append(float(parameters[5]))
            volumes.append(float(parameters[6]))
    return open_times, open_prices, high_prices, low_prices, close_prices, volumes, close_times


class Parameters:
    """Container describing one strategy configuration and its measured profit."""

    def __init__(self, rsi_sell, rsi_buy, sma_sell, sma_buy, atr_threshold,
                 stop_loss, take_profit, profit, calculated_profit):
        self.RSI_SELL_THRESHOLD = rsi_sell
        self.RSI_BUY_THRESHOLD = rsi_buy
        self.SMA_SELL_THRESHOLD = sma_sell
        self.SMA_BUY_THRESHOLD = sma_buy
        self.ATR_THRESHOLD = atr_threshold
        self.STOP_LOSS = stop_loss
        self.TAKE_PROFIT = take_profit
        self.profit = profit
        self.calculated_profit = calculated_profit


def calculate_profit(side, price1, price2, fee_percentage=0.05):
    """Realised profit of a round-trip trade, net of the Binance 0.05% fee per side."""
    global quantity
    if side == 'BUY':
        buy_price = float(price1)
        sell_price = float(price2)
    if side == 'SELL':
        sell_price = float(price1)
        buy_price = float(price2)
    total_sell = sell_price * quantity
    total_buy = buy_price * quantity
    total_fee = (total_sell + total_buy) * (fee_percentage / 100)
    return total_sell - total_buy - total_fee


class Order(threading.Thread):
    """A single open position; resolves once its stop loss or take profit is hit."""

    def __init__(self, order_id, side, open_price, stop_loss_price, take_profit_price,
                 open_time, rsi, sma, atr):
        super().__init__()
        self.side = side
        self.order_id = order_id
        self.daemon = True
        self.open_price = float(open_price)
        self.event = None
        self.stop_loss_price = float(stop_loss_price)
        self.take_profit_price = float(take_profit_price)
        self.calculated_profit = 0
        self.close_price = 0
        self.open_time = open_time
        self.close_time = None
        self.atr = atr
        self.sma = sma
        self.rsi = rsi

    def check_status(self, low_price, high_price, close_time):
        self.close_time = close_time
        if self.side == 'SELL':
            if low_price < self.take_profit_price:  # take profit hit
                self.calculated_profit = calculate_profit('SELL', self.open_price, self.take_profit_price)
                self.close_price = self.take_profit_price
                self.event.set()
                return True
            elif high_price > self.stop_loss_price:  # stop loss hit
                self.calculated_profit = calculate_profit('SELL', self.open_price, self.stop_loss_price)
                self.close_price = self.stop_loss_price
                self.event.set()
                return True
        if self.side == 'BUY':
            if low_price < self.stop_loss_price:  # stop loss hit
                self.calculated_profit = calculate_profit('BUY', self.open_price, self.stop_loss_price)
                self.close_price = self.stop_loss_price
                self.event.set()
                return True
            elif high_price > self.take_profit_price:  # take profit hit
                self.calculated_profit = calculate_profit('BUY', self.open_price, self.take_profit_price)
                self.close_price = self.take_profit_price
                self.event.set()
                return True
        return False

    def run(self):
        global calculated_profit
        global lock
        self.event = threading.Event()
        try:
            self.event.wait()
            lock.acquire()
            calculated_profit += self.calculated_profit
            lock.release()
        except Exception as e:
            logger.error(f"Error in thread: {e}")


def get_stop_loss_function(atr, k):
    # Exponential stop-loss sizing from ATR (Phase C). k == Ks.
    return 1400 * (np.exp(k * atr) - 1)


def get_take_profit_function(k):
    # Exponential take-profit multiplier applied to the stop loss (Phase C). k == Kt.
    return np.exp(0.8459 * k) - 1


def get_current_RSI(close_prices, length=14):
    return ta.rsi(pd.Series(close_prices), length=length).iloc[-1]


def get_current_SMA(rsis, length=14):
    return ta.sma(pd.Series(rsis), length=length).iloc[-1]


def get_current_ATR(high_prices, close_prices, low_prices, length=14):
    """ATR expressed as a percentage of the last close price."""
    high_series = pd.Series(high_prices)
    close_series = pd.Series(close_prices)
    low_series = pd.Series(low_prices)
    tr = ta.true_range(high_series, low_series, close_series, length=length)
    scaled_tr = deque(maxlen=100)
    last_close_price = close_prices[-1]
    for t in tr:
        scaled_tr.append(t * (100 / last_close_price))
    sma = ta.sma(pd.Series(scaled_tr), length=length)
    return sma.iloc[-1]


def initialize_RSIs(close_prices):
    """Warm up the RSI series over the first half of the provided closes."""
    rsis = deque(maxlen=50)
    series = pd.Series(close_prices)
    for i in range(0, int(len(series) / 2)):
        subset = series[i:(i + 50)]
        rsis.append(ta.rsi(subset, length=14).iloc[-1])
    return rsis


def format_solid_parameters(arr1, arr2):
    """Render pairs of profitable parameter bounds as "{lo - hi}, ..." for logging."""
    return ", ".join([f"{{{round(n1, 2)} - {round(n2, 2)}}}" for n1, n2 in zip(arr1, arr2)])


def backtesting(num_days, k, days_back, ks, kt):
    """
    Run the strategy over one window and return the profit plus market statistics.

    Returns:
        (calculated_profit, avg_price, avg_atr, avg_rsi, avg_sma, avg_volume,
         price_trend, volume_trend, price_frequency, volume_frequency)
    """
    global calculated_profit

    atr_values, rsi_values, sma_values, volume_values = [], [], [], []
    close_prices = deque(maxlen=100)
    high_prices = deque(maxlen=100)
    low_prices = deque(maxlen=100)
    volume = deque(maxlen=k)
    calculated_profit = 0

    open_times, open_p, high_p, low_p, close_p, volumes, close_times = get_previous_candles(
        days=num_days, days_back=days_back)
    num_of_candles = len(high_p)

    for i in range(100):
        close_prices.append(close_p[i])
        high_prices.append(high_p[i])
        low_prices.append(low_p[i])
        volume.append(volumes[i])
    rsis = initialize_RSIs(close_prices)

    order = None
    for i in range(100, num_of_candles):
        rsi = get_current_RSI(close_prices)
        rsis.append(rsi)
        sma = get_current_SMA(rsis)
        atr = get_current_ATR(high_prices, close_prices, low_prices)
        atr_values.append(atr)
        rsi_values.append(rsi)
        sma_values.append(sma)
        close_prices.append(close_p[i])
        high_prices.append(high_p[i])
        low_prices.append(low_p[i])
        avg_volume = mean(list(volume)[0:-1])
        volume.append(volumes[i])
        volume_values.append(volumes[i])
        open_price = float(open_p[i])
        high_price = float(high_p[i])
        low_price = float(low_p[i])
        open_time_ms = int((pd.to_datetime(open_times[i], unit='ms') + timedelta(hours=1)).timestamp() * 1000)

        if order is None:
            if (rsi < RSI_SELL_THRESHOLD and rsi < sma and sma < SMA_SELL_THRESHOLD
                    and ATR_THRESHOLD < atr < ATR_THRESHOLD1
                    and volumes[i - 1] > VOLUME_FACTOR * avg_volume):
                stop_loss = get_stop_loss_function(atr, ks)
                take_profit = stop_loss * get_take_profit_function(kt)
                order = Order(i, 'SELL', open_price, open_price + stop_loss, open_price - take_profit,
                              open_time_ms, rsi, sma, atr)
                order.start()
            if (rsi > RSI_BUY_THRESHOLD and rsi > sma and sma > SMA_BUY_THRESHOLD
                    and ATR_THRESHOLD < atr < ATR_THRESHOLD1
                    and volumes[i - 1] > VOLUME_FACTOR * avg_volume):
                stop_loss = get_stop_loss_function(atr, ks)
                take_profit = stop_loss * get_take_profit_function(kt)
                order = Order(i, 'BUY', open_price, open_price - stop_loss, open_price + take_profit,
                              open_time_ms, rsi, sma, atr)
                order.start()

        if order is not None and order.check_status(low_price, high_price, open_time_ms):
            order = None

    # Market statistics measured over the whole window.
    avg_price = int(mean(list(close_p)))
    avg_volume_value = int(mean(volume_values))
    price_trend = volume_trend = price_frequency = volume_frequency = 0
    for price in close_p:
        if float(price) > 1.015 * avg_price or float(price) < 0.985 * avg_price:
            price_frequency += 1
        if int(price) > avg_price:
            price_trend += 1
        elif int(price) < avg_price:
            price_trend -= 1
    for vol in volumes:
        if float(vol) > 1.1 * avg_volume_value or float(vol) < 0.9 * avg_volume_value:
            volume_frequency += 1
        if int(vol) > avg_volume_value:
            volume_trend += 1
        elif int(vol) < avg_volume_value:
            volume_trend -= 1

    return (calculated_profit, avg_price, mean(atr_values), mean(rsi_values), mean(sma_values),
            avg_volume_value, price_trend, volume_trend, price_frequency, volume_frequency)


def find_best_parameters(date, prev_days=5):
    """Sweep Ks/Kt for a single date and return the best calculated profit found."""
    global ATR_THRESHOLD
    global ATR_THRESHOLD1
    days_back = int(days_from_now(date - timedelta(days=prev_days)))
    cp_max = 0
    ATR_THRESHOLD = 0.4
    ATR_THRESHOLD1 = 1
    ks = 0.8
    while ks < 1.6:
        kt = 0.8
        while kt < 1.65:
            cp = backtesting(prev_days, 70, days_back, ks, kt)[0]
            if cp > cp_max:
                cp_max = cp
            kt += 0.05
        ks += 0.05
    return cp_max


def main():
    global RSI_SELL_THRESHOLD, RSI_BUY_THRESHOLD
    global SMA_SELL_THRESHOLD, SMA_BUY_THRESHOLD
    global ATR_THRESHOLD, ATR_THRESHOLD1
    global VOLUME_FACTOR
    global quantity

    quantity = 0.002
    read_lines_from_file()

    RSI_SELL_THRESHOLD = 40
    RSI_BUY_THRESHOLD = 60
    SMA_SELL_THRESHOLD = 55
    SMA_BUY_THRESHOLD = 45
    VOLUME_FACTOR = 1.5

    # Phase B: tune (Ks, Kt) -> Stop Loss / Take Profit separately inside each ATR band.
    # Each band can be made to look profitable in isolation; see docs/phase_B.md for why the
    # combined out-of-sample run does not simply add these profits up.
    atr_bands = [(0.25, 0.30), (0.30, 0.40), (0.40, 0.50), (0.50, 0.99)]
    num_days = 300
    days_back = 300
    with open("profit_per_atr_band.csv", "w") as file:
        file.write("ATR_LOW,ATR_HIGH,BEST_KS,BEST_KT,BEST_PROFIT\n")
        for low, high in atr_bands:
            ATR_THRESHOLD = low
            ATR_THRESHOLD1 = high
            best_ks = best_kt = 0.0
            best_profit = 0.0
            ks = 0.8
            while ks < 1.65:
                kt = 0.8
                while kt < 1.65:
                    cp = backtesting(num_days, 70, days_back, ks, kt)[0]
                    if cp > best_profit:
                        best_profit = cp
                        best_ks, best_kt = ks, kt
                    kt += 0.1
                ks += 0.1
            file.write(f"{low:.2f},{high:.2f},{best_ks:.2f},{best_kt:.2f},{best_profit:.2f}\n")


if __name__ == "__main__":
    main()
