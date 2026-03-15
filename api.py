"""
GL Dashboard API
----------------
Run:   python api.py
Open:  http://localhost:5000
"""

import os
import sqlite3
from datetime import datetime
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__)

BASE_DIR  = os.path.dirname(__file__)
DB_PATH   = os.path.join(BASE_DIR, "gl.db")


# ── helpers ────────────────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def query(sql, params=()):
    conn = get_conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def scalar(sql, params=()):
    conn = get_conn()
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row[0] if row else None

def fmt_label(ym):
    """'2023-01'  ->  \"Jan '23\" """
    return datetime.strptime(ym, "%Y-%m").strftime("%b '%y")

def fmt_currency(v):
    """Format number as $1.23M / $456K / $789"""
    if v is None:
        return None
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if abs(v) >= 1_000:
        return f"${v/1_000:.0f}K"
    return f"${v:.0f}"

def prior_month_key(ym):
    """'2023-03' -> '2023-02',  '2023-01' -> '2022-12'"""
    dt = datetime.strptime(ym, "%Y-%m")
    m = dt.month - 1 or 12
    y = dt.year if dt.month > 1 else dt.year - 1
    return f"{y}-{m:02d}"

def prior_year_key(ym):
    """'2023-03' -> '2022-03'"""
    dt = datetime.strptime(ym, "%Y-%m")
    return f"{dt.year - 1}-{dt.month:02d}"


# ── routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "dashboard.html")


@app.route("/api/dashboard")
def dashboard():

    # ── all months available in the DB ────────────────────────────────────
    all_months = [
        r["month"] for r in query("""
            SELECT DISTINCT substr(posting_date, 1, 7) AS month
            FROM gl_transactions
            ORDER BY month
        """)
    ]
    if not all_months:
        return jsonify({"error": "No data in database"}), 404

    # last 12 months as the display window
    window   = all_months[-12:]
    latest   = window[-1]
    prev_mon = window[-2] if len(window) >= 2 else None

    # ── revenue by month (all months in DB) ───────────────────────────────
    rev_by_month = {
        r["month"]: r["revenue"]
        for r in query("""
            SELECT substr(posting_date, 1, 7) AS month,
                   SUM(posting_amount)        AS revenue
            FROM gl_transactions
            WHERE account_group_l1 = 'REVENUE'
            GROUP BY month
        """)
    }

    # ── revenue by region by month ────────────────────────────────────────
    region_rows = query("""
        SELECT substr(posting_date, 1, 7) AS month,
               location,
               SUM(posting_amount)        AS revenue
        FROM gl_transactions
        WHERE account_group_l1 = 'REVENUE'
        GROUP BY month, location
    """)

    def region_rev(month, loc):
        return next(
            (r["revenue"] for r in region_rows
             if r["month"] == month and r["location"] == loc), 0
        )

    # ── build trend arrays ────────────────────────────────────────────────
    current_rev = [rev_by_month.get(m) for m in window]
    prior_rev   = [rev_by_month.get(prior_year_key(m)) for m in window]

    na_rev   = [region_rev(m, "North America") for m in window]
    emea_rev = [region_rev(m, "EMEA")          for m in window]
    asia_rev = [region_rev(m, "Asia")          for m in window]

    # ── KPIs ──────────────────────────────────────────────────────────────
    latest_rev = rev_by_month.get(latest, 0)
    prev_rev   = rev_by_month.get(prev_mon, 0) if prev_mon else 0

    # YoY
    yoy_mon = prior_year_key(latest)
    yoy_rev = rev_by_month.get(yoy_mon)
    yoy_pct = round((latest_rev - yoy_rev) / yoy_rev * 100, 1) if yoy_rev else None
    yoy_abs = round(latest_rev - yoy_rev)                        if yoy_rev else None

    # MoM
    mom_pct = round((latest_rev - prev_rev) / prev_rev * 100, 1) if prev_rev else None
    mom_abs = round(latest_rev - prev_rev)                        if prev_rev else None

    # Gross Margin  (Revenue - COGS) / Revenue
    cogs = scalar("""
        SELECT SUM(posting_amount)
        FROM gl_transactions
        WHERE account_group_l1 = 'EXPENSE'
          AND account_name      = 'Cost of Goods Sold'
          AND substr(posting_date, 1, 7) = ?
    """, (latest,)) or 0

    gross_margin_pct = (
        round((latest_rev - cogs) / latest_rev * 100, 1)
        if latest_rev else None
    )

    # Top-5 customers — latest month
    top5_rows = query("""
        SELECT customer, SUM(posting_amount) AS revenue
        FROM gl_transactions
        WHERE account_group_l1 = 'REVENUE'
          AND customer IS NOT NULL AND customer != ''
          AND substr(posting_date, 1, 7) = ?
        GROUP BY customer
        ORDER BY revenue DESC
        LIMIT 5
    """, (latest,))

    top5_total      = sum(r["revenue"] for r in top5_rows)
    top5_pct_total  = round(top5_total / latest_rev * 100, 1) if latest_rev else 0

    cum = 0.0
    top5_out = []
    for r in top5_rows:
        pct  = round(r["revenue"] / latest_rev * 100, 1) if latest_rev else 0
        cum += pct
        top5_out.append({
            "customer":       r["customer"],
            "revenue":        r["revenue"],
            "pct":            pct,
            "cumulative_pct": round(cum, 1),
        })

    # ── Variance table (prev month vs latest, by region) ─────────────────
    REGIONS = [
        ("North America", "#58a6ff"),
        ("EMEA",          "#bc8cff"),
        ("Asia",          "#f0883e"),
    ]
    variance = []
    total_prev = total_curr = 0

    for loc, color in REGIONS:
        prev_loc = region_rev(prev_mon, loc) if prev_mon else 0
        curr_loc = region_rev(latest,   loc)
        chg_abs  = curr_loc - prev_loc
        chg_pct  = round(chg_abs / prev_loc * 100, 1) if prev_loc else None
        share    = round(curr_loc / latest_rev * 100, 1) if latest_rev else 0
        total_prev += prev_loc
        total_curr += curr_loc
        variance.append({
            "region":     loc,
            "color":      color,
            "prev":       prev_loc,
            "curr":       curr_loc,
            "change_abs": chg_abs,
            "change_pct": chg_pct,
            "share":      share,
        })

    tot_chg     = total_curr - total_prev
    tot_chg_pct = round(tot_chg / total_prev * 100, 1) if total_prev else None
    variance.append({
        "region":     "Total",
        "color":      None,
        "prev":       total_prev,
        "curr":       total_curr,
        "change_abs": tot_chg,
        "change_pct": tot_chg_pct,
        "share":      100.0,
    })

    # ── response ──────────────────────────────────────────────────────────
    return jsonify({
        "latest_month_label": fmt_label(latest),
        "prev_month_label":   fmt_label(prev_mon) if prev_mon else None,
        "kpis": {
            "total_revenue":    latest_rev,
            "yoy_growth_pct":   yoy_pct,
            "yoy_growth_abs":   yoy_abs,
            "mom_growth_pct":   mom_pct,
            "mom_growth_abs":   mom_abs,
            "gross_margin_pct": gross_margin_pct,
            "top5_pct":         top5_pct_total,
        },
        "trend": {
            "labels":  [fmt_label(m) for m in window],
            "current": current_rev,
            "prior":   prior_rev,
        },
        "by_region": {
            "labels":        [fmt_label(m) for m in window],
            "north_america": na_rev,
            "emea":          emea_rev,
            "asia":          asia_rev,
        },
        "variance_table":  variance,
        "top5_customers":  top5_out,
    })


# ── run ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n  Dashboard: http://localhost:5000\n")
    app.run(debug=True, port=5000)
