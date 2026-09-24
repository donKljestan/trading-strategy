"""
Phase C: fitting the exponential Stop Loss curve.

Phase B showed that hand-picked, fixed Stop Loss / Take Profit values were brittle. Phase C
replaces them with a smooth function of volatility (ATR): small stops in calm markets, larger
stops in volatile ones. Four target (ATR, StopLoss) points were chosen by hand to give the
desired shape, and an exponential model a*exp(b*x)+c was fitted to them with scipy.

The fitted shape is the basis of get_stop_loss_function() in testing.py, where an extra
coefficient Ks is exposed so the stop can still be tuned:

    StopLoss   = 1400 * (e^(Ks * ATR) - 1)
    TakeProfit = StopLoss * (e^(0.8459 * Kt) - 1)
"""

import numpy as np
from scipy.optimize import curve_fit

# Target (ATR, StopLoss) points chosen to give the desired risk curve.
atr = np.array([0.225, 0.275, 0.35, 0.45])
stop_loss = np.array([620, 1400, 1700, 2000])


def model(x, a, b, c):
    return a * np.exp(b * x) + c


params, _ = curve_fit(model, atr, stop_loss, maxfev=5000)
a, b, c = params
print(f"a={a}, b={b}, c={c}")
