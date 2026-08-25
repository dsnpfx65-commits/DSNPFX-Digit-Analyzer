# DSNPFX Import Status

The recovered DSNPFX intelligence engine is now connected to the Market Insight redesign on `redesign-market-insight`.

- Recovered source files reviewed: 108
- Core runtime dependency closure imported into GitHub
- Active Python compile check: PASS
- Market Insight engine bridge smoke test: PASS
- Targeted V8.3 production / market-qualification / calibration tests run locally: 12 passed
- Live tick payload corrected to publish `displayed_quote` and `digit` for the dashboard
- Standard Volatility markets remain production-eligible; 1-second markets remain shadow-learning markets
- Predictions remain `WAIT / NO EDGE` unless the production accuracy gate publishes a verified signal
- Secret scan: no hard-coded Deriv API token found; token configuration is environment-based
- Temporary bootstrap files were removed after the verified import

No live trade execution is enabled by this import, and no live trading credentials are stored in the repository.
