"""
Phase E: is Ks/Kt (and profit) predictable from market features?

Random Forest feature-importance + SHAP on the parameter/outcome dataset (paramsBezTime.csv).
Together with the correlation/regression results summarised in docs/phase_E.md, the honest
conclusion is that market features explain very little of the profitable Ks/Kt or of profit
itself. (Kept as documentation of the analysis; see docs/phase_E.md for the numbers.)
"""

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error, r2_score
import shap

data = pd.read_csv("paramsBezTime.csv", delimiter=";")

features = ["ATR", "AverageNumberOfTrades", "NumberOfTrades", "Momentum", "PriceFrequency"]
X = data[features]
y = data["Profit"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

model = RandomForestRegressor(n_estimators=100, random_state=42)
model.fit(X_train, y_train)

importance_df = pd.DataFrame({"Feature": features, "Importance": model.feature_importances_})
importance_df["Percentage_Contribution"] = importance_df["Importance"] / importance_df["Importance"].sum() * 100
print(importance_df[["Feature", "Percentage_Contribution"]])

# Model quality on held-out data.
y_pred = model.predict(X_test)
print(f"MSE: {mean_squared_error(y_test, y_pred):.2f}")
print(f"R^2: {r2_score(y_test, y_pred):.3f}")

# SHAP for interpretability of feature contributions.
explainer = shap.TreeExplainer(model)
shap_values = explainer.shap_values(X)
shap.summary_plot(shap_values, X, plot_type="bar")
