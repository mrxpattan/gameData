#!/usr/bin/env python3
"""
collect.py - WinGo 30S real-time continuous data collector.

Collects draw results from the public WinGo 30S API/OSS endpoint and saves them to CSV.
Deduplicates records by issueNumber, verifies sequence continuity, and detects missing draws.

Usage:
    python collect.py                        # Single poll (merges recent draws into CSV)
    python collect.py --loop 30              # Continuous polling every 30 seconds
    python collect.py --loop 25 --minutes 30  # Test run for 30 minutes with verification report
"""
import argparse
import csv
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

URL = "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json"
FIELDS = ["issueNumber", "number", "color", "premium", "sum"]


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def make_session():
    s = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
    })
    return s


def fetch_page(session, url, page=1, page_param="pageNo"):
    params = {"ts": int(time.time() * 1000)}
    if page > 1:
        params[page_param] = page
    r = session.get(url, params=params, timeout=15)
    r.raise_for_status()
    j = r.json()
    if j.get("code") != 0 or not isinstance(j.get("data"), dict):
        raise RuntimeError(f"unexpected response: {str(j)[:200]}")
    return j["data"]


def load(path):
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        return {r["issueNumber"]: r for r in csv.DictReader(f)}


def save(path, rows):
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for k in sorted(rows, key=int):
            w.writerow(rows[k])
    tmp.replace(path)


def find_gaps(issues):
    """Check for gaps in issue numbers within each day."""
    by_day = defaultdict(list)
    for i in issues:
        by_day[i[:8]].append((int(i[8:]), i))
    gaps = []
    for seq in by_day.values():
        seq.sort()
        for (a, ia), (b, ib) in zip(seq, seq[1:]):
            if b - a > 1:
                gaps.append((ia, ib, b - a - 1))
    return sorted(gaps)


def run_once(a, session=None):
    if session is None:
        session = make_session()

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    existing = load(out)
    newest = max(map(int, existing), default=None)
    fresh, error = {}, None

    try:
        for page in range(1, a.max_pages + 1):
            d = fetch_page(session, a.url, page, a.page_param)
            server_page = int(d.get("pageNo", page))
            if page > 1 and server_page != page:
                break
            rows = [{k: str(x.get(k, "")) for k in FIELDS} for x in d.get("list", [])]
            if not rows:
                break
            for r in rows:
                if r["issueNumber"] not in existing:
                    fresh[r["issueNumber"]] = r
            if newest is not None and min(int(r["issueNumber"]) for r in rows) <= newest + 1:
                break
            if page >= int(d.get("totalPage") or page):
                break
            if page < a.max_pages:
                time.sleep(a.delay)
    except Exception as e:
        error = e

    if error and existing:
        log(f"[ERROR] Fetch failed: {error!r} - skipped, will retry on next poll")
        return {}, len(existing), error

    merged = {**existing, **fresh}
    if fresh:
        save(out, merged)

    gaps = find_gaps(merged)
    missing = sum(g[2] for g in gaps)
    
    status_str = f"+{len(fresh):2d} new | Total: {len(merged):,} draws | Gaps: {len(gaps)} ({missing} missing)"
    if fresh:
        newest_id = max(fresh.keys())
        status_str += f" | Latest issue: {newest_id}"
    log(status_str)

    return fresh, len(merged), error


def main():
    p = argparse.ArgumentParser(description="Collect WinGo 30S draw history into CSV.")
    p.add_argument("--url", default=URL)
    p.add_argument("--out", default="data/wingo_30s.csv")
    p.add_argument("--max-pages", type=int, default=1,
                   help="Maximum pages to attempt (default 1, since server only serves latest 10 draws)")
    p.add_argument("--page-param", default="pageNo",
                   help="Query-string name for pagination")
    p.add_argument("--delay", type=float, default=0.5,
                   help="Pause between multi-page requests (if any)")
    p.add_argument("--loop", type=int, default=0, metavar="SECONDS",
                   help="Continuous loop: poll every SECONDS (recommended: 25 to 30)")
    p.add_argument("--minutes", type=float, default=0,
                   help="Stop loop after MINUTES (e.g. --minutes 30 for verification test)")
    p.add_argument("--duration", type=int, default=0,
                   help="Stop loop after SECONDS (overrides --minutes)")
    a = p.parse_args()

    session = make_session()

    if not a.loop:
        fresh_dict, total_cnt, err = run_once(a, session)
        sys.exit(1 if err else 0)

    duration_sec = a.duration if a.duration > 0 else int(a.minutes * 60)
    start_time = time.time()
    end_time = start_time + duration_sec if duration_sec > 0 else None

    log("=" * 70)
    log(f"Starting continuous collector | Poll interval: {a.loop}s")
    if duration_sec > 0:
        log(f"Target duration: {duration_sec}s ({duration_sec / 60:.1f} minutes)")
    log(f"Output CSV: {a.out}")
    log("=" * 70)

    session_issues = set()
    polls_count = 0
    initial_rows = len(load(Path(a.out)))

    try:
        while True:
            polls_count += 1
            fresh_dict, current_total, err = run_once(a, session)
            session_issues.update(fresh_dict.keys())

            if end_time and time.time() >= end_time:
                break

            time.sleep(a.loop)

    except KeyboardInterrupt:
        log("Collector stopped by user (Ctrl+C)")

    elapsed = time.time() - start_time
    final_rows = load(Path(a.out))
    
    # Check session gaps
    session_gaps = find_gaps(session_issues)
    session_missing = sum(g[2] for g in session_gaps)

    # Check overall file gaps
    all_gaps = find_gaps(final_rows)
    all_missing = sum(g[2] for g in all_gaps)

    log("=" * 70)
    log(f"COLLECTION VERIFICATION REPORT (Elapsed: {elapsed / 60:.2f} mins, {polls_count} polls)")
    log(f"  Starting rows in file:      {initial_rows:,}")
    log(f"  Fresh draws in this run:    {len(session_issues):,}")
    log(f"  Final total rows in file:   {len(final_rows):,}")
    log(f"  Gaps during this test run:  {len(session_gaps)} ({session_missing} missing draws)")
    log(f"  Total all-time file gaps:   {len(all_gaps)} ({all_missing} missing draws)")
    
    if len(session_issues) > 0 and session_missing == 0:
        log("  >>> VERDICT: 100% CONSTANT & OK - ZERO GAPS DURING RUN! <<<")
    else:
        log("  >>> VERDICT: Review missing draws above <<<")
    log("=" * 70)


if __name__ == "__main__":
    main()
