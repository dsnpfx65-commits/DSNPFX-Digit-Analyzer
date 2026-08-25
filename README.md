# DSNPFX Digit Analyzer

DSNPFX Intelligence Market Insight AI and Deriv digit prediction project.

## Redesign branch

The `redesign-market-insight` branch imports the recovered DSNPFX runtime and the new Market Insight dashboard while preserving the evidence-first production gate. Candidate digits remain `WAIT / NO EDGE` unless the production accuracy gate publishes a verified prediction.

## Run locally / Codespaces

```bash
python -m pip install -r requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

The Bot Setup screen is currently a control UI only. It does not place live Deriv trades.

Runtime import is automated on this redesign branch.
