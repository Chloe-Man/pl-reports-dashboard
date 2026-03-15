# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

A P&L / Revenue dashboard for **Aurora Dynamics**. Monthly General Ledger CSV files are loaded into a SQLite database (`gl.db`), served by a Flask API, and visualized in a single-page dark-themed HTML dashboard using Chart.js.

## Dependencies

Python 3 with `flask` and `gunicorn` (see `requirements.txt`). No frontend build — Chart.js is loaded via CDN in `dashboard.html`.

```bash
pip install -r requirements.txt
```

## Commands

```bash
# Load GL data into SQLite (creates gl.db if needed; re-upload is idempotent)
python upload_gl.py "Raw GL Data by Month/GL_012024.csv"
python upload_gl.py "Raw GL Data by Month/GL_*2024.csv"   # shell glob for a full year

# Check what's loaded
python upload_gl.py --list

# Remove a month (format: MMYYYY)
python upload_gl.py --delete 012024

# Start the dashboard locally (opens at http://localhost:5000)
# PORT env var overrides the default port
python api.py
```

## Architecture

Three source files — no build step, no bundler, no tests:

- **upload_gl.py** — CLI tool that reads CSV files from `Raw GL Data by Month/` into the `gl_transactions` table in `gl.db`. Column mapping from CSV headers to DB columns is defined in `COLUMN_MAP`. Re-uploading the same file replaces its rows (keyed on `source_file`). Handles glob expansion internally (needed on Windows where the shell doesn't expand `*`).
- **api.py** — Flask app with a single data endpoint `GET /api/dashboard` that computes KPIs (revenue, YoY/MoM growth, gross margin, top-5 customers), trend arrays, regional breakdowns, and a variance table. All queries hit `gl.db` directly via `sqlite3`. Serves `dashboard.html` at `/`.
- **dashboard.html** — Self-contained SPA (no framework). Fetches `/api/dashboard` on load and renders KPI cards, a 12-month trend line, stacked bar by region, variance table, and top-5 customer chart using Chart.js 4.x.

## Data Model

Single table `gl_transactions` with indexes on `posting_date`, `account_id`, `entity`, `location`, `scenario`, `source_file`, `account_group_l0`, `account_group_l1`. Key columns used in dashboard queries:

- `account_group_l1` — `'REVENUE'` or `'EXPENSE'` (used to separate revenue from COGS)
- `account_name` — `'Cost of Goods Sold'` for gross margin calc
- `posting_date` — date string, first 7 chars (`YYYY-MM`) used for monthly grouping
- `location` — region values: `'North America'`, `'EMEA'`, `'Asia'`
- `customer` — used for top-5 customer ranking
- `posting_amount` — the monetary value aggregated in all reports

Additional columns available but not yet surfaced: `vendor`, `entity`, `department`, `account_group_l0`, `account_group_l2`, `intercompany`, `debit`/`credit`, `posting_currency`/`reporting_currency`, `currency_eop_rate`/`currency_avg_rate`.

## GL CSV File Naming

Files in `Raw GL Data by Month/` follow the pattern `GL_MMYYYY.csv` (e.g., `GL_012024.csv` for January 2024). Available data spans 2023–2025 (all 12 months for each year). The `--delete` command expects the `MMYYYY` portion.

## Deployment

The dashboard is hosted on **Render** (free tier) at `https://pl-reports-dashboard.onrender.com`. GitHub repo: `https://github.com/Chloe-Man/pl-reports-dashboard.git`.

- **render.yaml** — Render Blueprint that defines the web service config (build command, start command, plan).
- **Start command:** `gunicorn api:app --bind 0.0.0.0:10000` (Render uses port 10000).
- **Auto-deploy is off** (public git repo, not connected via Git Provider) — use **Manual Deploy → Deploy latest commit** in the Render dashboard after pushing.
- `gl.db` is committed to the repo so Render has the data. After loading new months locally, push the updated `gl.db` and manually redeploy.
- Free tier spins down with inactivity; first request after idle can take ~50 seconds.

## Workflow: Adding a New Month

1. `python upload_gl.py "Raw GL Data by Month/GL_MMYYYY.csv"` — load locally
2. `git add gl.db && git commit -m "Update gl.db with <month> data" && git push` — push to GitHub
3. Manual Deploy on Render dashboard — update the live site
