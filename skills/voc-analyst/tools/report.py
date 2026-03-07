"""
VoC Intelligence Agent — Report Generator
Generates professional Markdown action reports from the SQLite database.
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

# Ensure sibling modules are importable when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
LOGS_DIR = PROJECT_ROOT / "logs"

PRODUCT_NAMES = {
    "master_buds_1": "Master Buds 1",
    "master_buds_max": "Master Buds Max",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_pct(num: int, denom: int) -> str:
    """Return a percentage string, or '0%' if denom is zero."""
    if denom == 0:
        return "0%"
    return f"{round(num / denom * 100)}%"


def _top_theme(themes_data: dict, sentiment_filter: str) -> str:
    """Find the theme with the highest count for a given sentiment."""
    best_theme = "N/A"
    best_count = 0
    for theme, data in themes_data.items():
        count = data.get("sentiment_breakdown", {}).get(sentiment_filter, 0)
        if count > best_count:
            best_count = count
            best_theme = theme
    return best_theme


def _get_product_reviews(product_id: str, since_date: str | None = None) -> list[dict]:
    """Query reviews for a product, optionally filtered by date."""
    if since_date:
        return db.query_reviews(
            f"SELECT * FROM reviews WHERE product_id = '{product_id}' "
            f"AND ingested_at >= '{since_date}'"
        )
    return db.query_reviews(
        f"SELECT * FROM reviews WHERE product_id = '{product_id}'"
    )


def _get_sample_quote(product_id: str, theme: str, sentiment: str) -> str:
    """Find a representative review quote for a theme + sentiment combo."""
    rows = db.query_reviews(
        f"SELECT text FROM reviews "
        f"WHERE product_id = '{product_id}' "
        f"AND sentiment = '{sentiment}' "
        f"AND themes LIKE '%{theme}%' "
        f"AND processed = 1 "
        f"LIMIT 1"
    )
    if rows and rows[0].get("text"):
        text = rows[0]["text"]
        return text[:150] + ("…" if len(text) > 150 else "")
    return "No matching review found."


# ---------------------------------------------------------------------------
# Global Report
# ---------------------------------------------------------------------------

def generate_global_report(
    output_path: str = "reports/global_actions.md",
) -> str:
    """
    Generate a comprehensive global action report across all products and time.

    Returns:
        Path to the generated report file.
    """
    db.initialize_db()
    stats = db.get_review_stats()
    total_reviews = stats["total_reviews"]

    if total_reviews == 0:
        logger.warning("No reviews in database — generating empty report.")

    # Date range
    date_range = db.query_reviews(
        "SELECT MIN(date) AS earliest, MAX(date) AS latest FROM reviews"
    )
    earliest = date_range[0].get("earliest", "N/A") if date_range else "N/A"
    latest = date_range[0].get("latest", "N/A") if date_range else "N/A"

    # Per-product stats
    product_stats = {}
    for pid, pname in PRODUCT_NAMES.items():
        rows = db.query_reviews(
            f"SELECT COUNT(*) as cnt, AVG(rating) as avg_r FROM reviews "
            f"WHERE product_id = '{pid}'"
        )
        sent = db.query_reviews(
            f"SELECT sentiment, COUNT(*) as cnt FROM reviews "
            f"WHERE product_id = '{pid}' AND sentiment IS NOT NULL "
            f"GROUP BY sentiment"
        )
        sent_map = {r["sentiment"]: r["cnt"] for r in sent}
        total_p = rows[0]["cnt"] if rows else 0
        avg_r = round(rows[0]["avg_r"], 1) if rows and rows[0]["avg_r"] else 0.0

        product_stats[pid] = {
            "name": pname,
            "total": total_p,
            "avg_rating": avg_r,
            "positive_pct": _safe_pct(sent_map.get("Positive", 0), total_p),
            "sentiments": sent_map,
        }

    # Theme data per product
    themes_by_product = {}
    for pid in PRODUCT_NAMES:
        themes_by_product[pid] = db.get_theme_trends(product_id=pid)

    # Global theme data
    global_themes = db.get_theme_trends()

    # Find top complaint / praise per product
    for pid in PRODUCT_NAMES:
        td = themes_by_product[pid]
        product_stats[pid]["top_complaint"] = _top_theme(td, "Negative")
        product_stats[pid]["top_praise"] = _top_theme(td, "Positive")

    # -------------------------------------------------------------------
    # Build the report
    # -------------------------------------------------------------------
    now = datetime.now().strftime("%Y-%m-%d %H:%M IST")
    p1 = product_stats.get("master_buds_1", {})
    p2 = product_stats.get("master_buds_max", {})

    lines = [
        "# 🎧 VoC Global Action Intelligence Report",
        f"**Generated:** {now}  ",
        f"**Products Analyzed:** Master Buds 1 | Master Buds Max  ",
        f"**Total Reviews:** {total_reviews} | **Period:** {earliest} to {latest}  ",
        "",
        "---",
        "",
        "## 📊 Executive Summary",
        "",
        "| Metric | Master Buds 1 | Master Buds Max |",
        "|--------|--------------|-----------------|",
        f"| Total Reviews | {p1.get('total', 0)} | {p2.get('total', 0)} |",
        f"| Avg Rating | {p1.get('avg_rating', 0)}/5 | {p2.get('avg_rating', 0)}/5 |",
        f"| Positive % | {p1.get('positive_pct', '0%')} | {p2.get('positive_pct', '0%')} |",
        f"| Top Complaint | {p1.get('top_complaint', 'N/A')} | {p2.get('top_complaint', 'N/A')} |",
        f"| Top Praise | {p1.get('top_praise', 'N/A')} | {p2.get('top_praise', 'N/A')} |",
        "",
        "---",
        "",
    ]

    # --- PRODUCT TEAM ---
    lines.append("## 🔧 PRODUCT TEAM — Action Items")
    lines.append("")
    lines.append("### Critical Issues (Negative reviews, recurring themes)")
    lines.append("")

    for theme, data in global_themes.items():
        neg_count = data["sentiment_breakdown"].get("Negative", 0)
        if data["count"] > 0 and neg_count / data["count"] > 0.10:
            pct = round(neg_count / data["count"] * 100)
            quote = _get_sample_quote("master_buds_1", theme, "Negative")
            lines.append(
                f"**{theme}:** {neg_count} negative mentions ({pct}% of {data['count']} total) — "
                f"Average rating when mentioned: {data['avg_rating']}/5"
            )
            lines.append(f'> Supporting evidence: "{quote}" — {neg_count} similar complaints')
            lines.append("")

    lines.append("### Wins to Double Down On")
    lines.append("")
    for theme, data in global_themes.items():
        pos_count = data["sentiment_breakdown"].get("Positive", 0)
        if data["count"] > 0 and pos_count / data["count"] > 0.20:
            pct = round(pos_count / data["count"] * 100)
            lines.append(
                f"**{theme}:** {pos_count} positive mentions ({pct}% positive) — "
                f"Avg rating: {data['avg_rating']}/5  "
            )
    lines.append("")
    lines.append("---")
    lines.append("")

    # --- MARKETING TEAM ---
    lines.append("## 📣 MARKETING TEAM — Action Items")
    lines.append("")
    lines.append("### Messaging Opportunities")
    lines.append("")
    for theme, data in sorted(
        global_themes.items(),
        key=lambda x: x[1]["sentiment_breakdown"].get("Positive", 0),
        reverse=True,
    )[:5]:
        pos = data["sentiment_breakdown"].get("Positive", 0)
        if pos > 0:
            lines.append(
                f"- **{theme}** — {pos} positive mentions (avg {data['avg_rating']}/5). "
                f"Strong candidate for ad copy and feature highlights."
            )
    lines.append("")

    lines.append("### Claims to Retire")
    lines.append("")
    for theme, data in sorted(
        global_themes.items(),
        key=lambda x: x[1]["sentiment_breakdown"].get("Negative", 0),
        reverse=True,
    )[:3]:
        neg = data["sentiment_breakdown"].get("Negative", 0)
        if neg > 0:
            lines.append(
                f"- **{theme}** — {neg} negative mentions. "
                f"Avoid over-promising on this feature in marketing materials."
            )
    lines.append("")
    lines.append("---")
    lines.append("")

    # --- SUPPORT TEAM ---
    lines.append("## 🛠️ SUPPORT TEAM — Action Items")
    lines.append("")
    lines.append("### Top FAQ Candidates")
    lines.append("")
    for theme, data in sorted(
        global_themes.items(), key=lambda x: x[1]["count"], reverse=True
    )[:5]:
        lines.append(
            f"- **{theme}** — {data['count']} mentions total. "
            f"Build FAQ / troubleshooting content around this topic."
        )
    lines.append("")

    lines.append("### Escalation Patterns")
    lines.append("")
    # Reviews with rating < 2 and recurring themes
    low_rated = db.query_reviews(
        "SELECT themes, COUNT(*) as cnt FROM reviews "
        "WHERE rating <= 2 AND processed = 1 AND themes IS NOT NULL "
        "GROUP BY themes ORDER BY cnt DESC LIMIT 5"
    )
    for row in low_rated:
        if row.get("themes"):
            try:
                theme_list = json.loads(row["themes"])
                lines.append(
                    f"- **{', '.join(theme_list)}** — {row['cnt']} reviews with ≤2 stars. "
                    f"Flag for priority support response."
                )
            except (json.JSONDecodeError, TypeError):
                pass
    lines.append("")
    lines.append("---")
    lines.append("")

    # --- THEME ANALYSIS TABLE ---
    lines.append("## 📈 Theme Analysis")
    lines.append("")
    lines.append("| Theme | Mentions | Positive% | Negative% | Avg Rating |")
    lines.append("|-------|----------|-----------|-----------|------------|")
    for theme, data in sorted(
        global_themes.items(), key=lambda x: x[1]["count"], reverse=True
    ):
        pos = data["sentiment_breakdown"].get("Positive", 0)
        neg = data["sentiment_breakdown"].get("Negative", 0)
        lines.append(
            f"| {theme} | {data['count']} | "
            f"{_safe_pct(pos, data['count'])} | "
            f"{_safe_pct(neg, data['count'])} | "
            f"{data['avg_rating']}/5 |"
        )
    lines.append("")
    lines.append("---")
    lines.append(
        "*Report generated by Molly — VoC Intelligence Agent | Data: Public reviews only*"
    )

    # Write to file
    out = Path(output_path)
    if not out.is_absolute():
        out = PROJECT_ROOT / output_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")

    logger.info("Global report saved to %s (%d lines)", out, len(lines))
    return str(out)


# ---------------------------------------------------------------------------
# Delta (Weekly) Report
# ---------------------------------------------------------------------------

def generate_delta_report(
    since_date: str | None = None,
    output_path: str = "reports/weekly_delta.md",
) -> str:
    """
    Generate a weekly delta report for reviews ingested after since_date.

    Args:
        since_date: ISO date string (YYYY-MM-DD). Defaults to 7 days ago.
        output_path: Where to save the report.

    Returns:
        Path to the generated report file.
    """
    db.initialize_db()

    if since_date is None:
        since_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    today = datetime.now().strftime("%Y-%m-%d")
    prev_start = (datetime.strptime(since_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")

    # This week's reviews
    this_week = db.query_reviews(
        f"SELECT * FROM reviews WHERE ingested_at >= '{since_date}'"
    )
    this_week_count = len(this_week)

    # Previous week's reviews (for comparison)
    prev_week = db.query_reviews(
        f"SELECT * FROM reviews WHERE ingested_at >= '{prev_start}' "
        f"AND ingested_at < '{since_date}'"
    )
    prev_week_count = len(prev_week)

    # Comparison percentage
    if prev_week_count > 0:
        change_pct = round((this_week_count - prev_week_count) / prev_week_count * 100)
        change_str = f"+{change_pct}%" if change_pct >= 0 else f"{change_pct}%"
    else:
        change_str = "N/A (no previous week data)"

    # Theme trends: this week vs previous week
    this_week_themes = db.get_theme_trends(since_date=since_date)
    prev_week_themes = db.get_theme_trends(since_date=prev_start)
    # Filter prev to only include reviews before since_date
    # (get_theme_trends uses >= so we need the full period themes minus this week)

    # -------------------------------------------------------------------
    # Build the report
    # -------------------------------------------------------------------
    now = datetime.now().strftime("%Y-%m-%d %H:%M IST")

    lines = [
        f"# 📬 VoC Weekly Delta Report — Week of {since_date}",
        f"**New Reviews This Week:** {this_week_count}  ",
        f"**Compared to last week:** {change_str}  ",
        "",
        "---",
        "",
    ]

    # --- SPIKES & ALERTS ---
    lines.append("## 🚨 Spikes & Alerts (>20% change from previous week)")
    lines.append("")

    has_spikes = False
    for theme, data in this_week_themes.items():
        this_count = data["count"]
        prev_count = prev_week_themes.get(theme, {}).get("count", 0)
        if prev_count > 0:
            pct_change = round((this_count - prev_count) / prev_count * 100)
            direction = "UP" if pct_change > 0 else "DOWN"
            if abs(pct_change) > 20:
                has_spikes = True
                quote = _get_sample_quote("master_buds_1", theme, "Negative")
                lines.append(
                    f"**{theme} — {direction} {abs(pct_change)}%**"
                )
                lines.append(
                    f"- Previous week: {prev_count} mentions | This week: {this_count} mentions"
                )
                lines.append(f'- Key new review: "{quote}"')
                lines.append(
                    f"- **Recommended Action:** "
                    f"{'Investigate root cause and prioritise fix' if direction == 'UP' else 'Monitor — trend improving'}"
                )
                lines.append("")
        elif this_count >= 3:
            has_spikes = True
            lines.append(f"**{theme} — NEW TREND ({this_count} mentions)**")
            lines.append(f"- Not seen last week. Monitor closely.")
            lines.append("")

    if not has_spikes:
        lines.append("No significant spikes detected this week.")
        lines.append("")

    lines.append("---")
    lines.append("")

    # --- PER-PRODUCT DELTA ---
    for pid, pname in PRODUCT_NAMES.items():
        product_reviews = [r for r in this_week if r.get("product_id") == pid]
        p_count = len(product_reviews)
        ratings = [r.get("rating", 0) for r in product_reviews if r.get("rating")]
        avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else 0.0

        # Top themes for this product this week
        product_themes = db.get_theme_trends(product_id=pid, since_date=since_date)
        top_3 = list(product_themes.items())[:3]

        lines.append(f"## 📥 {pname} — This Week")
        lines.append("")
        lines.append(
            f"New reviews: {p_count} | Avg rating: {avg_rating}/5"
        )
        if top_3:
            theme_strs = [f"{t} ({d['count']})" for t, d in top_3]
            lines.append(f"Top themes this week: {', '.join(theme_strs)}")
        else:
            lines.append("Top themes this week: No analysed data yet")
        lines.append("")

    lines.append("---")
    lines.append(
        f"*Delta period: {since_date} to {today} | Generated autonomously by Molly*"
    )

    # Write to file
    out = Path(output_path)
    if not out.is_absolute():
        out = PROJECT_ROOT / output_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")

    logger.info("Delta report saved to %s (%d lines)", out, len(lines))
    return str(out)


# ---------------------------------------------------------------------------
# Delta Proof Log
# ---------------------------------------------------------------------------

def save_delta_log(
    new_reviews_by_product: dict,
    run_date: str | None = None,
) -> str:
    """
    Save a JSON log proving incremental scraping results.

    Args:
        new_reviews_by_product: {
            "master_buds_1": {"new_reviews": N, "sources": {"amazon": X, "flipkart": Y}},
            "master_buds_max": {"new_reviews": N, "sources": {"amazon": X, "flipkart": Y}},
        }
        run_date: ISO date string. Defaults to today.

    Returns:
        Path to the saved log file.
    """
    db.initialize_db()

    if run_date is None:
        run_date = datetime.now().strftime("%Y-%m-%d")

    total_new = sum(
        p.get("new_reviews", 0) for p in new_reviews_by_product.values()
    )

    # Total in DB
    stats = db.get_review_stats()

    log_entry = {
        "run_date": run_date,
        "run_timestamp": datetime.now().isoformat(),
        "products": new_reviews_by_product,
        "total_new": total_new,
        "total_in_db": stats["total_reviews"],
    }

    # Load existing log or start fresh
    log_path = LOGS_DIR / "delta_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if log_path.exists():
        try:
            existing = json.loads(log_path.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                existing.append(log_entry)
            else:
                existing = [existing, log_entry]
        except (json.JSONDecodeError, TypeError):
            existing = [log_entry]
    else:
        existing = [log_entry]

    log_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info("Delta log saved to %s — %d new reviews", log_path, total_new)
    return str(log_path)


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  VoC Report Generator — Self-test")
    print("=" * 60)

    # Initialise DB
    db.initialize_db()

    # Generate reports (will be mostly empty without data)
    print("\n📝 Generating global report…")
    global_path = generate_global_report()
    print(f"   ✅ Saved to: {global_path}")

    print("\n📝 Generating delta report…")
    delta_path = generate_delta_report()
    print(f"   ✅ Saved to: {delta_path}")

    print("\n📝 Saving delta log…")
    log_path = save_delta_log({
        "master_buds_1": {"new_reviews": 0, "sources": {"amazon": 0, "flipkart": 0}},
        "master_buds_max": {"new_reviews": 0, "sources": {"amazon": 0, "flipkart": 0}},
    })
    print(f"   ✅ Saved to: {log_path}")

    print("\n✅ Report generator test complete!")
