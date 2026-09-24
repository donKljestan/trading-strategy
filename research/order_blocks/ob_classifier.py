"""
Decision-tree classifier that filters raw order-block candidates down to
high-confidence order blocks (Phase G, Smart Money Concepts).

The rule-based detectors in ``order_blocks.py`` and ``structure.py`` produce many
candidate zones, most of which never lead to a clean move. This module trains a
small ``DecisionTreeClassifier`` on manually validated order blocks and then
keeps only the predictions that pass a strict post-filter: high predicted
probability, elevated volume, a Fair Value Gap and above-average volatility.

The trained model is persisted alongside this file as ``order_block_model.pkl``
so it can be reused for inference without retraining.
"""

import joblib
import pandas as pd
from sklearn.tree import DecisionTreeClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import MinMaxScaler

FEATURES = ["volume", "Volume_MA", "FVG", "ATR"]
TARGET = "OrderBlockLabel"
MODEL_PATH = "order_block_model.pkl"


def build_features(data):
    """Derive the technical features consumed by the classifier."""
    data = data.copy()
    data["Volume_MA"] = data["volume"].rolling(window=50).mean()
    data["FVG"] = (data["high"].shift(1) < data["low"]).astype(int)
    data["ATR"] = data["high"] - data["low"]
    data["Volume_MA"] = data["Volume_MA"].fillna(data["volume"].mean())
    return data


def train_order_block_classifier(data, model_path=MODEL_PATH):
    """
    Train the order-block quality classifier.

    ``data`` must contain the ``OrderBlockLabel`` column (1 for manually
    validated order blocks, 0 otherwise). Features are min-max scaled before a
    depth-limited decision tree is fitted. After prediction, a strict rule-based
    post-filter keeps only the strongest order blocks.

    Returns the fitted model, the fitted scaler and the subset of
    high-confidence order blocks.
    """
    data = build_features(data)
    data = data.dropna(subset=FEATURES + [TARGET])

    scaler = MinMaxScaler()
    X = scaler.fit_transform(data[FEATURES])
    y = data[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    model = DecisionTreeClassifier(max_depth=5, min_samples_split=10)
    model.fit(X_train, y_train)
    print(f"Model accuracy: {model.score(X_test, y_test):.2f}")

    data["OrderBlockPred"] = model.predict(scaler.transform(data[FEATURES]))
    data["OrderBlockProb"] = model.predict_proba(scaler.transform(data[FEATURES]))[:, 1]

    high_confidence = data[
        (data["OrderBlockPred"] == 1)
        & (data["OrderBlockProb"] >= 0.9)
        & (data["volume"] > 1.5 * data["Volume_MA"])
        & (data["FVG"] == 1)
        & (data["ATR"] > data["ATR"].mean())
    ]
    print(f"High-confidence order blocks detected: {len(high_confidence)}")

    joblib.dump({"model": model, "scaler": scaler}, model_path)
    return model, scaler, high_confidence


def predict_order_blocks(data, model_path=MODEL_PATH, min_probability=0.9):
    """
    Score new data with a previously trained classifier bundle and return the
    rows that clear ``min_probability`` and the strict post-filter.
    """
    bundle = joblib.load(model_path)
    model, scaler = bundle["model"], bundle["scaler"]

    data = build_features(data)
    features = scaler.transform(data[FEATURES])
    data["OrderBlockPred"] = model.predict(features)
    data["OrderBlockProb"] = model.predict_proba(features)[:, 1]

    return data[
        (data["OrderBlockPred"] == 1)
        & (data["OrderBlockProb"] >= min_probability)
        & (data["volume"] > 1.5 * data["Volume_MA"])
        & (data["FVG"] == 1)
        & (data["ATR"] > data["ATR"].mean())
    ]
