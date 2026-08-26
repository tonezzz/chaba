# Gold / THB / USD Causality App

A small static web app that visualizes the gold/THB/USD causality analysis.

## Run it

1. Make sure the analysis has run and the generated files exist:
   ```bash
   .venv/bin/python analyze.py
   ```
   This produces `data/aligned.csv`, `data/returns.csv`, and `data/results.json`.

2. Start the local server:
   ```bash
   .venv/bin/python app/serve.py
   ```

3. Open the URL printed by the server, normally:
   ```
   http://localhost:8050/app/
   ```

## What it shows

- Normalized price levels for XAU/USD, USD/THB, and USD/EUR.
- Daily log returns.
- Cross-correlogram of XAU/USD and USD/THB returns.
- Impulse-response of XAU/USD to THB and USD/EUR shocks from the VAR.
- The full results JSON.

The app is intentionally dependency-light: it uses Plotly and Papa Parse from a CDN.
