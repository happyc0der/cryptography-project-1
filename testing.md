# Testing Guide

## Project Overview

This project has two test files:

1. `test_protocol.py` – checks core correctness:

- Valid ranges, waste, and gap rules
- Message and pointer consistency
- Reproducible results with the same seed

2. `eval_protocol.py` – measures performance:

- Runs scenarios with 1–5 active senders
- Compares wasted pads vs expected baseline
- Outputs summary table and summary.csv

## How to Run

**Run the basic tests:**

```bash
pytest -q test_protocol.py
```

**Run the performance test:**

```bash
python eval_protocol.py
```
