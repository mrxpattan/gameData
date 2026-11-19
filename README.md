# WinGo 30S Dataset Collector

Continuous dataset collection system for WinGo 30S game draws, designed to build a dataset of 10,000–15,000 draws for AI model training.

## Features
- **Zero Gaps / Deduplication:** Deduplicates each draw by `issueNumber` and identifies any sequence holes.
- **Continuous Polling:** Polls every 25 seconds to capture all 30-second draws within the server's 10-draw (5-minute) rolling buffer.
- **Atomic File Writing:** Always writes to `.tmp` first and replaces `.csv` atomically to protect against corruption.
- **GitHub Actions Integration:** Supports continuous batch collection workflows.

## Dataset Format (`data/wingo_30s.csv`)
Columns:
- `issueNumber`: Unique draw identifier (`YYYYMMDD` + Game ID `10005` + Daily Sequence Counter)
- `number`: Draw number (0–9)
- `color`: Draw color (`green`, `red`, `red,violet`, `green,violet`)
- `premium`: Winning premium
- `sum`: Total sum

## Usage

### Run Locally (Continuous Background Loop)
```bash
python collect.py --loop 25
```

### Run for a Specific Duration (e.g. 30 Minutes or 5 Hours)
```bash
python collect.py --loop 25 --minutes 30
python collect.py --loop 25 --minutes 300
```

### Analyze Pattern & Trainability
```bash
python analyze.py
```
