#!/usr/bin/env python3
"""
analyze.py - check the collected draws for ANY learnable structure before you train a model.

    pip install pandas numpy scipy scikit-learn
    python analyze.py [data/wingo_30s.csv]

Three questions, cheapest first:
  1. Are all ten digits equally likely?                    (chi-square test)
  2. Does the previous digit change the next one's odds?   (chi-square test on pairs)
  3. Can a model trained on the past beat blind guessing on later draws it never saw?
"""
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier

ALPHA = 0.01   # p-values below this count as "something non-random shows up"
K = 10         # the model sees the previous K digits

path = sys.argv[1] if len(sys.argv) > 1 else "data/wingo_30s.csv"
df = pd.read_csv(path, dtype=str).sort_values("issueNumber").reset_index(drop=True)
n = df["number"].astype(int).to_numpy()
N = len(n)
if N < 300:
    sys.exit(f"Only {N} rows - collect more data first.")
if n.min() < 0 or n.max() > 9:
    sys.exit("Unexpected values in the 'number' column (expected 0-9).")

# ---------------------------------------------------------------- data checks
by_day = defaultdict(list)
for i in df["issueNumber"]:
    by_day[i[:8]].append(int(i[8:]))
missing = 0
for seq in by_day.values():
    seq.sort()
    missing += sum(b - a - 1 for a, b in zip(seq, seq[1:]) if b - a > 1)
print(f"\n{N:,} draws, {df['issueNumber'].iloc[0]} -> {df['issueNumber'].iloc[-1]}")
print(f"duplicates: {df['issueNumber'].duplicated().sum()} | missing draws (gaps): {missing}")
if N < 3000:
    print("note: under ~3,000 rows these tests can only catch big biases.")

# ------------------------------------------------- 1) are the digits uniform?
counts = np.bincount(n, minlength=10)
p_freq = stats.chisquare(counts).pvalue
print("\n1) Digit frequencies (10.0% each if fair)")
print("   " + "  ".join(f"{d}:{c / N:5.1%}" for d, c in enumerate(counts)))
print(f"   chi-square p-value = {p_freq:.3f}")

# --------------------------------------------- 2) does the last digit matter?
pairs = np.zeros((10, 10), dtype=int)
np.add.at(pairs, (n[:-1], n[1:]), 1)
p_pairs = stats.chi2_contingency(pairs).pvalue
print("\n2) Does the previous digit change the next one?")
print(f"   same digit twice in a row: {(n[1:] == n[:-1]).mean():.1%} (10.0% if independent)")
print(f"   chi-square p-value = {p_pairs:.3f}")

# ------------------------------------ 3) can a model beat guessing, out of sample?
X = np.column_stack([n[i:N - K + i] for i in range(K)])   # previous K digits
y = n[K:]
cut = int(len(y) * 0.8)                                    # train on the past, test on the future
Xtr, Xte = X[:cut], X[cut:]
print(f"\n3) Model trained on the first {cut:,} draws, tested on the last {len(y) - cut:,}")

model_ps = []
for name, target, chance in [("digit 0-9", y, 0.10), ("big/small", (y >= 5).astype(int), 0.50)]:
    ytr, yte = target[:cut], target[cut:]
    model = HistGradientBoostingClassifier(max_iter=100, random_state=0).fit(Xtr, ytr)
    hits = int((model.predict(Xte) == yte).sum())
    base = (yte == np.bincount(ytr).argmax()).mean()      # "always guess the commonest"
    p = stats.binomtest(hits, len(yte), chance, alternative="greater").pvalue
    model_ps.append(p)
    print(f"   {name:<10} model {hits / len(yte):5.1%} | always-the-commonest {base:5.1%} "
          f"| pure chance {chance:4.0%} | p = {p:.3f}")

# ------------------------------------------------------------------- verdict
print()
if min(p_freq, p_pairs, *model_ps) < ALPHA:
    print("Verdict: something non-random shows up. Re-run on newer data to see whether it holds,")
    print("and check the CSV for collection errors first (one p < 0.01 in 4 tests can be luck).")
else:
    print("Verdict: no evidence of any pattern. The draws look random, so there is nothing")
    print("for a model to learn - any accuracy above chance you see elsewhere is noise or leakage.")
