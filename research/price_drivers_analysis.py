"""
Phase F: what really drives price -- and the level-vs-return trap.

Random Forest feature importance on the full 18-column dataset (values.csv), for two targets:
the open price *level* and the price *change* (close - open). Comparing the two exposes a spurious
result -- a doubly-smoothed feature dominates the price level but is meaningless for the change.
See docs/phase_F.md. (Kept as documentation of the analysis; not run here.)
"""

import pandas as pd
from sklearn.ensemble import RandomForestRegressor

data = pd.read_csv("values.csv")

features = [
    "RSI", "SMA", "ATR", "AverageATR", "Volume", "AverageVolume",
    "NumOfTrades", "AverageNumberOfTrades", "AverageOfAverageNumberOfTrades",
    "PriceFrequency", "AveragePriceFrequency", "QuoteAssetVolume",
    "AverageQuoteAssetVolume", "TakerBuyBaseAssetVolume", "AverageTakerBuyBaseAssetVolume",
]
X = data[features]

targets = {
    "open price (level)": data["OpenPrice"],
    "price change (close - open)": data["ClosePrice"] - data["OpenPrice"],
}

for name, y in targets.items():
    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X, y)
    importance = pd.DataFrame({"Feature": features, "Importance": model.feature_importances_})
    importance["Percentage_Contribution"] = importance["Importance"] / importance["Importance"].sum() * 100
    print(f"\nTarget: {name}")
    print(importance[["Feature", "Percentage_Contribution"]].sort_values("Percentage_Contribution", ascending=False))
