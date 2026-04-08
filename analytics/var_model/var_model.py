"""
Vector Autoregression (VAR) Model for Retail Banking Analytics.

This module builds a VAR model using synthetic monthly time series data
representative of key retail banking metrics:
  - transaction_volume : total number of transactions per month
  - avg_balance        : average account balance (NOK)
  - new_accounts       : number of new accounts opened per month
  - interest_rate      : prevailing base interest rate (%)

The pipeline covers:
  1. Synthetic data generation (or loading from CSV)
  2. Stationarity testing (ADF)
  3. Optimal lag selection (AIC / BIC / HQIC / FPE)
  4. VAR model fitting
  5. Diagnostic checks (Durbin-Watson, normality, whiteness)
  6. Granger causality tests
  7. Impulse Response Functions (IRF)
  8. Forecast Error Variance Decomposition (FEVD)
  9. Out-of-sample forecasting with confidence intervals

Usage
-----
    python var_model.py                   # generate data, fit, and report
    python var_model.py --data input.csv  # use external CSV instead
    python var_model.py --forecast 12     # forecast 12 steps ahead
"""

from __future__ import annotations

import argparse
import warnings
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # non-interactive backend for server environments

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.stats.stattools import durbin_watson
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import adfuller, grangercausalitytests
from statsmodels.tsa.vector_ar.var_model import VARResults

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_FORECAST_STEPS = 12
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------

def generate_synthetic_data(
    n_obs: int = 120,
    seed: int = 42,
) -> pd.DataFrame:
    """Create synthetic monthly retail-banking time series.

    Parameters
    ----------
    n_obs : int
        Number of monthly observations (default 120 = 10 years).
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    pd.DataFrame
        DataFrame indexed by month with four series.
    """
    rng = np.random.default_rng(seed)

    dates = pd.date_range(start="2015-01-01", periods=n_obs, freq="MS")

    # Base trends + seasonality + noise
    t = np.arange(n_obs)
    seasonal = np.sin(2 * np.pi * t / 12)

    # Transaction volume: upward trend + seasonality
    transaction_volume = (
        50_000
        + 200 * t
        + 5_000 * seasonal
        + rng.normal(0, 2_000, n_obs)
    )

    # Average balance: slow growth + slight seasonality
    avg_balance = (
        150_000
        + 500 * t
        + 3_000 * seasonal
        + rng.normal(0, 4_000, n_obs)
    )

    # New accounts: mild trend + seasonal spikes in Q1
    new_accounts = (
        300
        + 2 * t
        + 80 * seasonal
        + rng.normal(0, 30, n_obs)
    )
    new_accounts = np.maximum(new_accounts, 0).astype(int)

    # Interest rate: slow decline with small fluctuations
    interest_rate = (
        3.5
        - 0.015 * t
        + 0.1 * seasonal
        + rng.normal(0, 0.08, n_obs)
    )
    interest_rate = np.clip(interest_rate, 0.10, 6.0)

    df = pd.DataFrame(
        {
            "transaction_volume": transaction_volume,
            "avg_balance": avg_balance,
            "new_accounts": new_accounts,
            "interest_rate": interest_rate,
        },
        index=dates,
    )
    df.index.name = "month"
    return df


def load_data(filepath: str) -> pd.DataFrame:
    """Load time series data from a CSV file.

    The CSV must have a date column parseable as the index and numeric
    columns for each variable.
    """
    df = pd.read_csv(filepath, index_col=0, parse_dates=True)
    df.index.freq = pd.infer_freq(df.index)
    return df


# ---------------------------------------------------------------------------
# Stationarity
# ---------------------------------------------------------------------------

def test_stationarity(df: pd.DataFrame, significance: float = 0.05) -> pd.DataFrame:
    """Run Augmented Dickey-Fuller test on each series.

    Returns a summary DataFrame with test statistic, p-value,
    and whether the series is stationary at the given significance level.
    """
    results = []
    for col in df.columns:
        adf_stat, p_value, used_lag, n_obs, critical_values, _ = adfuller(
            df[col].dropna(), autolag="AIC"
        )
        results.append(
            {
                "series": col,
                "adf_statistic": round(adf_stat, 4),
                "p_value": round(p_value, 4),
                "lags_used": used_lag,
                "stationary": p_value < significance,
                "cv_1%": round(critical_values["1%"], 4),
                "cv_5%": round(critical_values["5%"], 4),
                "cv_10%": round(critical_values["10%"], 4),
            }
        )
    return pd.DataFrame(results)


def make_stationary(df: pd.DataFrame, significance: float = 0.05) -> tuple[pd.DataFrame, int]:
    """Difference the data until all series are stationary.

    Returns
    -------
    (stationary_df, diff_order) where diff_order is the number of
    differences applied (0, 1, or 2).
    """
    for d in range(3):
        stationarity = test_stationarity(df, significance)
        if stationarity["stationary"].all():
            return df, d
        df = df.diff().dropna()
    return df, 2


# ---------------------------------------------------------------------------
# Model selection & fitting
# ---------------------------------------------------------------------------

def select_lag_order(df: pd.DataFrame, max_lags: int = 15) -> None:
    """Evaluate and print information criteria across lag orders."""
    model = VAR(df)
    results = model.select_order(maxlags=max_lags)
    summary = results.summary()
    print("\n=== Lag Order Selection ===")
    print(summary)


def fit_var(df: pd.DataFrame, lag_order: Optional[int] = None, max_lags: int = 15) -> VARResults:
    """Fit the VAR model.

    If *lag_order* is None the optimal lag is chosen by AIC.
    """
    model = VAR(df)
    if lag_order is None:
        selection = model.select_order(maxlags=max_lags)
        lag_order = selection.aic
        print(f"\nOptimal lag order (AIC): {lag_order}")

    fitted = model.fit(lag_order)
    print("\n=== VAR Model Summary ===")
    print(fitted.summary())
    return fitted


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def run_diagnostics(fitted_model: VARResults) -> dict:
    """Run residual diagnostics on the fitted VAR model.

    Returns a dict with Durbin-Watson stats, whiteness test, and normality test.
    """
    diagnostics: dict = {}

    # Durbin-Watson (per equation)
    dw = durbin_watson(fitted_model.resid)
    dw_results = {
        col: round(val, 4) for col, val in zip(fitted_model.names, dw)
    }
    diagnostics["durbin_watson"] = dw_results
    print("\n=== Durbin-Watson Statistics ===")
    for col, val in dw_results.items():
        print(f"  {col}: {val}")

    # Whiteness (Portmanteau) test
    whiteness = fitted_model.test_whiteness(nlags=fitted_model.k_ar + 10, signif=0.05)
    diagnostics["whiteness"] = {
        "test_statistic": round(whiteness.test_statistic, 4),
        "p_value": round(whiteness.pvalue, 4),
        "conclusion": "white noise" if whiteness.pvalue > 0.05 else "autocorrelation present",
    }
    print("\n=== Whiteness (Portmanteau) Test ===")
    print(f"  Statistic: {diagnostics['whiteness']['test_statistic']}")
    print(f"  p-value:   {diagnostics['whiteness']['p_value']}")
    print(f"  Conclusion: {diagnostics['whiteness']['conclusion']}")

    # Normality test
    normality = fitted_model.test_normality(signif=0.05)
    diagnostics["normality"] = {
        "test_statistic": round(normality.test_statistic, 4),
        "p_value": round(normality.pvalue, 4),
        "conclusion": "normal" if normality.pvalue > 0.05 else "non-normal residuals",
    }
    print("\n=== Normality Test ===")
    print(f"  Statistic: {diagnostics['normality']['test_statistic']}")
    print(f"  p-value:   {diagnostics['normality']['p_value']}")
    print(f"  Conclusion: {diagnostics['normality']['conclusion']}")

    return diagnostics


# ---------------------------------------------------------------------------
# Granger Causality
# ---------------------------------------------------------------------------

def run_granger_causality(
    df: pd.DataFrame,
    max_lag: int = 4,
    significance: float = 0.05,
) -> pd.DataFrame:
    """Test pairwise Granger causality between all series.

    Returns a summary DataFrame.
    """
    results = []
    columns = df.columns.tolist()
    for target in columns:
        for predictor in columns:
            if target == predictor:
                continue
            test_data = df[[target, predictor]].dropna()
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", FutureWarning)
                    gc = grangercausalitytests(test_data, maxlag=max_lag, verbose=False)
                # Use the minimum p-value across lags (ssr_ftest)
                min_p = min(
                    gc[lag][0]["ssr_ftest"][1] for lag in range(1, max_lag + 1)
                )
                best_lag = min(
                    range(1, max_lag + 1),
                    key=lambda lag: gc[lag][0]["ssr_ftest"][1],
                )
                results.append(
                    {
                        "target": target,
                        "predictor": predictor,
                        "min_p_value": round(min_p, 4),
                        "best_lag": best_lag,
                        "granger_causes": min_p < significance,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "target": target,
                        "predictor": predictor,
                        "min_p_value": None,
                        "best_lag": None,
                        "granger_causes": None,
                        "error": str(exc),
                    }
                )
    gc_df = pd.DataFrame(results)
    print("\n=== Granger Causality Results ===")
    print(gc_df.to_string(index=False))
    return gc_df


# ---------------------------------------------------------------------------
# Impulse Response & Variance Decomposition
# ---------------------------------------------------------------------------

def plot_irf(fitted_model: VARResults, periods: int = 20) -> None:
    """Plot impulse response functions and save to output directory."""
    irf = fitted_model.irf(periods)
    fig = irf.plot(orth=True)
    fig.suptitle("Orthogonalized Impulse Response Functions", fontsize=14)
    fig.tight_layout()
    outpath = OUTPUT_DIR / "impulse_response.png"
    fig.savefig(outpath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\nIRF plot saved to {outpath}")


def plot_fevd(fitted_model: VARResults, periods: int = 20) -> None:
    """Plot Forecast Error Variance Decomposition and save."""
    fevd = fitted_model.fevd(periods)
    print("\n=== Forecast Error Variance Decomposition ===")
    print(fevd.summary())

    fig = fevd.plot()
    fig.suptitle("Forecast Error Variance Decomposition", fontsize=14)
    fig.tight_layout()
    outpath = OUTPUT_DIR / "variance_decomposition.png"
    fig.savefig(outpath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"FEVD plot saved to {outpath}")


# ---------------------------------------------------------------------------
# Forecasting
# ---------------------------------------------------------------------------

def forecast(
    fitted_model: VARResults,
    df_original: pd.DataFrame,
    steps: int = DEFAULT_FORECAST_STEPS,
    diff_order: int = 0,
) -> pd.DataFrame:
    """Generate out-of-sample forecasts.

    If the data was differenced, the forecasts are reverted back to levels.

    Returns
    -------
    pd.DataFrame with forecasted values in original scale.
    """
    lag_order = fitted_model.k_ar
    forecast_input = fitted_model.endog[-lag_order:]
    fc = fitted_model.forecast(y=forecast_input, steps=steps)

    last_date = df_original.index[-1]
    fc_index = pd.date_range(
        start=last_date + pd.DateOffset(months=1),
        periods=steps,
        freq="MS",
    )
    fc_df = pd.DataFrame(fc, index=fc_index, columns=df_original.columns)

    # Revert differencing
    if diff_order >= 1:
        last_level = df_original.iloc[-1]
        for i in range(len(fc_df)):
            fc_df.iloc[i] = fc_df.iloc[i] + last_level
            last_level = fc_df.iloc[i]

    print(f"\n=== {steps}-Step Forecast ===")
    print(fc_df.round(2).to_string())
    return fc_df


def plot_forecast(
    df_original: pd.DataFrame,
    fc_df: pd.DataFrame,
) -> None:
    """Plot historical data with forecasts appended."""
    n_vars = len(df_original.columns)
    fig, axes = plt.subplots(n_vars, 1, figsize=(12, 3 * n_vars), sharex=False)
    if n_vars == 1:
        axes = [axes]

    for ax, col in zip(axes, df_original.columns):
        ax.plot(df_original.index, df_original[col], label="Historical", linewidth=1.2)
        ax.plot(fc_df.index, fc_df[col], label="Forecast", linewidth=1.5, linestyle="--", color="red")
        ax.set_title(col, fontsize=12)
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

    fig.suptitle("VAR Model — Historical vs. Forecast", fontsize=14)
    fig.tight_layout()
    outpath = OUTPUT_DIR / "forecast.png"
    fig.savefig(outpath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\nForecast plot saved to {outpath}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="VAR model for Retail Banking Analytics",
    )
    parser.add_argument(
        "--data",
        type=str,
        default=None,
        help="Path to CSV with time series data (optional; generates synthetic data if omitted)",
    )
    parser.add_argument(
        "--forecast",
        type=int,
        default=DEFAULT_FORECAST_STEPS,
        dest="forecast_steps",
        help=f"Number of periods to forecast (default {DEFAULT_FORECAST_STEPS})",
    )
    parser.add_argument(
        "--max-lags",
        type=int,
        default=15,
        help="Maximum lag order to evaluate (default 15)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory for output plots and CSVs",
    )
    args = parser.parse_args(argv)

    global OUTPUT_DIR
    if args.output_dir:
        OUTPUT_DIR = Path(args.output_dir)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- 1. Load / generate data ---
    if args.data:
        print(f"Loading data from {args.data} ...")
        df_raw = load_data(args.data)
    else:
        print("Generating synthetic retail banking time series ...")
        df_raw = generate_synthetic_data()

    print(f"\nDataset shape: {df_raw.shape}")
    print(df_raw.head(10))
    print("\nDescriptive statistics:")
    print(df_raw.describe().round(2))

    # Save raw data
    raw_csv_path = OUTPUT_DIR / "raw_data.csv"
    df_raw.to_csv(raw_csv_path)
    print(f"\nRaw data saved to {raw_csv_path}")

    # --- 2. Stationarity testing ---
    print("\n" + "=" * 60)
    print("STEP 1: STATIONARITY TESTING")
    print("=" * 60)
    stationarity_raw = test_stationarity(df_raw)
    print("\nStationarity (raw levels):")
    print(stationarity_raw.to_string(index=False))

    df_stationary, diff_order = make_stationary(df_raw)
    if diff_order > 0:
        print(f"\nDifferenced {diff_order} time(s) to achieve stationarity.")
        stationarity_diff = test_stationarity(df_stationary)
        print("\nStationarity (after differencing):")
        print(stationarity_diff.to_string(index=False))
    else:
        print("\nAll series are already stationary at levels.")

    # --- 3. Lag selection ---
    print("\n" + "=" * 60)
    print("STEP 2: LAG ORDER SELECTION")
    print("=" * 60)
    select_lag_order(df_stationary, max_lags=args.max_lags)

    # --- 4. Fit VAR ---
    print("\n" + "=" * 60)
    print("STEP 3: VAR MODEL FITTING")
    print("=" * 60)
    fitted = fit_var(df_stationary, max_lags=args.max_lags)

    # --- 5. Diagnostics ---
    print("\n" + "=" * 60)
    print("STEP 4: RESIDUAL DIAGNOSTICS")
    print("=" * 60)
    run_diagnostics(fitted)

    # --- 6. Granger causality ---
    print("\n" + "=" * 60)
    print("STEP 5: GRANGER CAUSALITY")
    print("=" * 60)
    gc_results = run_granger_causality(df_stationary, max_lag=fitted.k_ar)

    # --- 7. IRF ---
    print("\n" + "=" * 60)
    print("STEP 6: IMPULSE RESPONSE FUNCTIONS")
    print("=" * 60)
    plot_irf(fitted)

    # --- 8. FEVD ---
    print("\n" + "=" * 60)
    print("STEP 7: VARIANCE DECOMPOSITION")
    print("=" * 60)
    plot_fevd(fitted)

    # --- 9. Forecast ---
    print("\n" + "=" * 60)
    print("STEP 8: FORECASTING")
    print("=" * 60)
    fc_df = forecast(fitted, df_raw, steps=args.forecast_steps, diff_order=diff_order)
    plot_forecast(df_raw, fc_df)

    # Save forecast
    fc_csv_path = OUTPUT_DIR / "forecast.csv"
    fc_df.to_csv(fc_csv_path)
    print(f"Forecast CSV saved to {fc_csv_path}")

    # Save Granger causality results
    gc_csv_path = OUTPUT_DIR / "granger_causality.csv"
    gc_results.to_csv(gc_csv_path, index=False)
    print(f"Granger causality CSV saved to {gc_csv_path}")

    print("\n" + "=" * 60)
    print("VAR MODEL PIPELINE COMPLETE")
    print("=" * 60)
    print(f"All outputs saved to: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
