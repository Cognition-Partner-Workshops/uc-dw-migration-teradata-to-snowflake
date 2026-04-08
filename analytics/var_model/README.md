# VAR Model — Retail Banking Analytics

A **Vector Autoregression (VAR)** model for analysing interdependencies among key retail-banking time series:

| Series | Description |
|---|---|
| `transaction_volume` | Monthly transaction count |
| `avg_balance` | Average account balance (NOK) |
| `new_accounts` | New accounts opened per month |
| `interest_rate` | Prevailing base interest rate (%) |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run with synthetic data (default)
python var_model.py

# Run with your own CSV
python var_model.py --data path/to/data.csv

# Custom forecast horizon
python var_model.py --forecast 24
```

## Pipeline Steps

1. **Data loading** — synthetic generator or CSV import
2. **Stationarity testing** — Augmented Dickey-Fuller; auto-differencing if needed
3. **Lag order selection** — AIC / BIC / HQIC / FPE comparison
4. **VAR model fitting** — optimal lag chosen by AIC
5. **Residual diagnostics** — Durbin-Watson, Portmanteau (whiteness), normality
6. **Granger causality** — pairwise tests between all series
7. **Impulse Response Functions** — orthogonalised IRF plots
8. **Forecast Error Variance Decomposition** — FEVD plots
9. **Out-of-sample forecasting** — with automatic differencing reversion

## Output

All artefacts are written to `output/`:

| File | Description |
|---|---|
| `raw_data.csv` | Input time series |
| `forecast.csv` | Forecasted values |
| `granger_causality.csv` | Pairwise Granger causality results |
| `impulse_response.png` | IRF plot |
| `variance_decomposition.png` | FEVD plot |
| `forecast.png` | Historical vs. forecast chart |

## CLI Options

| Flag | Default | Description |
|---|---|---|
| `--data` | *(synthetic)* | Path to input CSV |
| `--forecast` | `12` | Forecast horizon (months) |
| `--max-lags` | `15` | Maximum lag order to evaluate |
| `--output-dir` | `output/` | Directory for results |
