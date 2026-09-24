"""
Parameter-sweep backtester for the pre-order-blocks BTCUSDT strategy (15-minute candles).

Strategy summary:
  - Momentum: RSI, plus an SMA computed on the RSI series.
  - Volatility filter: ATR scaled to % of price, gated to an [ATR_LOW, ATR_HIGH] band.
  - Volume confirmation: current volume above VOLUME_FACTOR * recent average volume.
  - Risk sizing: Stop Loss / Take Profit come from exponential functions of ATR and the
    coefficients Ks, Kt. In Phase D, Ks and Kt are no longer fixed: they become *dynamic*
    functions of market conditions (ATR, number of trades, price frequency) through six
    coefficients A..F. See get_ks / get_kt.

main() runs the Phase D experiment: it grid-searches the six coefficients A..F that drive the
dynamic Ks/Kt model and records each combination's total profit to grid_search_ABCDEF.csv.
The goal is to let risk adapt to the market automatically -- and to expose how sensitive the
result is to those coefficients.

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
    open_prices, high_prices, low_prices, close_prices, volumes, num_trades = [], [], [], [], [], []
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
            num_trades.append(int(parameters[8]))  # number of trades in the candle
    return open_times, open_prices, high_prices, low_prices, close_prices, volumes, close_times, num_trades


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


def get_stop_loss_function(atr, ks, price):
    # Refined two-term exponential stop loss (Phase D): depends on both Ks and ATR.
    # Returns the stop-loss distance in price units.
    a, b, c = -0.0280, 2.0145, 0.411
    y = a * np.exp(b * ks) + c * np.exp(b * atr)  # y = % of price
    return (price / 100) * y


def get_take_profit_function(k):
    # Exponential take-profit multiplier over the stop loss. k == Kt.
    return np.exp(0.8459 * k) - 1


def get_ks(atr, average_atr, avg_num_trades, avg_of_avg_num_trades,
           price_frequency, average_price_frequency, A, B, C):
    """
    Phase D dynamic stop-loss coefficient.

    Ks rises with volatility (ATR), trading activity (number of trades) and how often price
    oscillates (price frequency), each measured relative to its own recent average, so the stop
    widens exactly when the market gets noisier.
    """
    ks0 = 0.7
    if average_price_frequency == 0:
        average_price_frequency = 1
    atr_p = (atr - average_atr) / average_atr + 0.5
    num_trades_p = (avg_num_trades - avg_of_avg_num_trades) / avg_of_avg_num_trades + 0.2
    price_freq_p = ((price_frequency - average_price_frequency) / average_price_frequency) / 100 + 0.02
    return ks0 + A * atr_p + B * num_trades_p + C * price_freq_p


def get_kt(atr, average_atr, avg_num_trades, avg_of_avg_num_trades,
           price_frequency, average_price_frequency, ks, D, E, F):
    """Phase D dynamic take-profit coefficient; anchored at 1.2 * Ks and shifted by D, E, F."""
    kt0 = 1.2 * ks
    if average_price_frequency == 0:
        average_price_frequency = 1
    atr_p = (atr - average_atr) / average_atr + 0.5
    num_trades_p = (avg_num_trades - avg_of_avg_num_trades) / avg_of_avg_num_trades + 0.2
    price_freq_p = ((price_frequency - average_price_frequency) / average_price_frequency) / 100 + 0.02
    return kt0 + D * atr_p + E * num_trades_p + F * price_freq_p


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


def backtesting(num_days, k, days_back, A, B, C, D, E, F):
    """
    Run the strategy over one window with dynamic (Ks, Kt) driven by coefficients A..F.

    Returns:
        (calculated_profit, avg_price, avg_atr, avg_rsi, avg_sma, avg_volume,
         price_trend, volume_trend, price_frequency, volume_frequency)
    """
    global calculated_profit

    atr_values, rsi_values, sma_values, volume_values, price_frequency_values = [], [], [], [], []
    avg_num_trades_series = []
    close_prices = deque(maxlen=100)
    high_prices = deque(maxlen=100)
    low_prices = deque(maxlen=100)
    volume = deque(maxlen=k)
    num_trades_window = deque(maxlen=k)
    calculated_profit = 0

    open_times, open_p, high_p, low_p, close_p, volumes, close_times, num_trades = get_previous_candles(
        days=num_days, days_back=days_back)
    num_of_candles = len(high_p)

    for i in range(100):
        close_prices.append(close_p[i])
        high_prices.append(high_p[i])
        low_prices.append(low_p[i])
        volume.append(volumes[i])
        num_trades_window.append(num_trades[i])
        avg_num_trades_series.append(mean(num_trades_window))
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
        num_trades_window.append(num_trades[i])

        # Rolling market conditions that drive the dynamic Ks/Kt.
        average_atr = mean(atr_values)
        avg_num_trades = mean(num_trades_window)
        avg_num_trades_series.append(avg_num_trades)
        avg_of_avg_num_trades = mean(avg_num_trades_series)
        window_avg_price = mean(close_prices)
        price_frequency = sum(1 for p in close_prices
                              if p > 1.015 * window_avg_price or p < 0.985 * window_avg_price)
        price_frequency_values.append(price_frequency)
        average_price_frequency = mean(price_frequency_values)

        open_price = float(open_p[i])
        high_price = float(high_p[i])
        low_price = float(low_p[i])
        open_time_ms = int((pd.to_datetime(open_times[i], unit='ms') + timedelta(hours=1)).timestamp() * 1000)

        if (order is None and ATR_THRESHOLD < atr < ATR_THRESHOLD1
                and volumes[i - 1] > VOLUME_FACTOR * avg_volume
                and avg_num_trades > 0.8 * avg_of_avg_num_trades):  # NUMBER_OF_TRADES_FACTOR = 0.8
            ks = get_ks(atr, average_atr, avg_num_trades, avg_of_avg_num_trades,
                        price_frequency, average_price_frequency, A, B, C)
            kt = get_kt(atr, average_atr, avg_num_trades, avg_of_avg_num_trades,
                        price_frequency, average_price_frequency, ks, D, E, F)
            if rsi < RSI_SELL_THRESHOLD and rsi < sma and sma < SMA_SELL_THRESHOLD:
                stop_loss = get_stop_loss_function(atr, ks, open_price)
                take_profit = stop_loss * get_take_profit_function(kt)
                order = Order(i, 'SELL', open_price, open_price + stop_loss, open_price - take_profit,
                              open_time_ms, rsi, sma, atr)
                order.start()
            elif rsi > RSI_BUY_THRESHOLD and rsi > sma and sma > SMA_BUY_THRESHOLD:
                stop_loss = get_stop_loss_function(atr, ks, open_price)
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
    ATR_THRESHOLD = 0.35
    ATR_THRESHOLD1 = 1.0

    # Phase D: grid-search the six coefficients A..F that drive the dynamic Ks/Kt model.
    # The step is deliberately coarse here (0.3); the real search was then refined around the best
    # region -- see docs/phase_D.md and results/grid_search_ABCDEF.csv.
    num_days = 300
    days_back = 300
    step = 0.3
    grid = [round(x, 2) for x in np.arange(-0.8, 0.81, step)]
    with open("grid_search_ABCDEF.csv", "w") as file:
        file.write("A,B,C,D,E,F,PROFIT\n")
        for A in grid:
            for B in grid:
                for C in grid:
                    for D in grid:
                        for E in grid:
                            for F in grid:
                                cp = backtesting(num_days, 70, days_back, A, B, C, D, E, F)[0]
                                file.write(f"{A},{B},{C},{D},{E},{F},{cp:.2f}\n")


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
