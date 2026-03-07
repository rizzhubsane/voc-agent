#!/usr/bin/env python3
"""
agent.py — VoC Intelligence Agent CLI
Main entry point for pipeline execution and conversational querying.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Import all tools
# ---------------------------------------------------------------------------
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "skills", "voc-analyst", "tools")
)
from scrape import scrape_reviews, mock_scrape_reviews  # noqa: E402
from db import (  # noqa: E402
    initialize_db,
    store_reviews,
    get_review_stats,
    get_theme_trends,
    query_reviews,
    log_ingestion_run,
)
from analyze import analyze_reviews, mock_analyze_reviews  # noqa: E402
from report import (  # noqa: E402
    generate_global_report,
    generate_delta_report,
    save_delta_log,
)
from query_engine import query_engine_run  # noqa: E402

# ---------------------------------------------------------------------------
# Product / URL config from .env
# ---------------------------------------------------------------------------
PRODUCTS = {
    "master_buds_1": {
        "name": "Master Buds 1",
        "urls": {
            "amazon": os.getenv("MASTER_BUDS_1_AMAZON_URL", ""),
            "flipkart": os.getenv("MASTER_BUDS_1_FLIPKART_URL", ""),
        },
    },
    "master_buds_max": {
        "name": "Master Buds Max",
        "urls": {
            "amazon": os.getenv("MASTER_BUDS_MAX_AMAZON_URL", ""),
            "flipkart": os.getenv("MASTER_BUDS_MAX_FLIPKART_URL", ""),
        },
    },
}


# ---------------------------------------------------------------------------
# Command: --ingest
# ---------------------------------------------------------------------------
def cmd_ingest(max_pages: int = 10):
    """Run the full scraping + storage pipeline for all products."""
    print("\n🦞 Starting weekly VoC ingestion pipeline...")
    print("=" * 60)

    initialize_db()
    delta_data = {}

    for product_id, product in PRODUCTS.items():
        product_name = product["name"]
        delta_data[product_id] = {"new_reviews": 0, "sources": {}}

        for source, url in product["urls"].items():
            if not url or "PRODUCT_ID_HERE" in url or "product-url-here" in url:
                print(f"⏭️  {product_name} ({source}): URL not configured — skipping")
                delta_data[product_id]["sources"][source] = 0
                continue

            print(f"\n📡 Scraping {product_name} from {source}…")
            reviews = scrape_reviews(product_id, source, url, max_pages=max_pages)

            if reviews:
                result = store_reviews(reviews, product_id, source)
                new = result["new_count"]
                skip = result["skipped_count"]
                total = result["total_in_db"]
                delta_data[product_id]["new_reviews"] += new
                delta_data[product_id]["sources"][source] = new
                print(
                    f"✅ {product_id} ({source}): "
                    f"{new} new reviews, {skip} skipped, {total} total in DB"
                )
            else:
                delta_data[product_id]["sources"][source] = 0
                print(f"⚠️  {product_id} ({source}): No reviews scraped")

    # Log ingestion per product
    for product_id, data in delta_data.items():
        stats = get_review_stats()
        total_for_product = stats["by_product"].get(product_id, 0)
        log_ingestion_run(product_id, data["new_reviews"], total_for_product)

    # Save delta proof
    save_delta_log(delta_data)

    # Summary
    total_new = sum(d["new_reviews"] for d in delta_data.values())
    print("\n" + "=" * 60)
    print(f"🎉 Ingestion complete! {total_new} total new reviews ingested.")
    for pid, d in delta_data.items():
        print(f"   {PRODUCTS[pid]['name']}: {d['new_reviews']} new")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Command: --analyze
# ---------------------------------------------------------------------------
def cmd_analyze(batch_size: int = 20):
    """Run LLM sentiment + theme analysis on unprocessed reviews."""
    print("\n🧠 Running sentiment and theme analysis…")
    print("=" * 60)

    initialize_db()
    result = analyze_reviews(product_id=None, batch_size=batch_size)

    print("\n📊 Analysis Results:")
    print(f"   Processed: {result['processed_count']} reviews")

    if result["sentiment_breakdown"]:
        print("\n   Sentiment Breakdown:")
        for sent, count in sorted(result["sentiment_breakdown"].items()):
            pct = round(count / result["processed_count"] * 100) if result["processed_count"] else 0
            bar = "█" * (pct // 5)
            print(f"     {sent:10s}: {count:4d} ({pct}%) {bar}")

    if result["theme_breakdown"]:
        print("\n   Theme Breakdown (top 10):")
        for theme, count in list(result["theme_breakdown"].items())[:10]:
            print(f"     {theme:30s}: {count}")

    print("=" * 60)


# ---------------------------------------------------------------------------
# Command: --report
# ---------------------------------------------------------------------------
def cmd_report():
    """Generate global and delta reports."""
    print("\n📝 Generating reports…")
    print("=" * 60)

    initialize_db()

    print("  → Global action report…")
    global_path = generate_global_report()
    print(f"    ✅ Saved to: {global_path}")

    print("  → Weekly delta report…")
    delta_path = generate_delta_report()
    print(f"    ✅ Saved to: {delta_path}")

    print("\n📊 Reports saved to reports/")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Command: --pipeline (full autonomous run)
# ---------------------------------------------------------------------------
def cmd_pipeline(max_pages: int = 10, batch_size: int = 20):
    """Run the full pipeline: ingest → analyze → report."""
    start = time.time()
    print("\n" + "🔷" * 30)
    print("  FULL AUTONOMOUS PIPELINE")
    print("🔷" * 30)

    print("\n[Step 1/3] INGESTION")
    cmd_ingest(max_pages=max_pages)

    print("\n[Step 2/3] ANALYSIS")
    cmd_analyze(batch_size=batch_size)

    print("\n[Step 3/3] REPORTING")
    cmd_report()

    elapsed = round(time.time() - start, 1)
    print("\n" + "🔷" * 30)
    print(f"  PIPELINE COMPLETE — {elapsed}s elapsed")
    print("🔷" * 30)


# ---------------------------------------------------------------------------
# Command: --query
# ---------------------------------------------------------------------------
def cmd_query(question: str):
    """Conversational database query using Groq Text-to-SQL engine."""
    print(f"\n🔍 Molly is analyzing your question: \"{question}\"")
    print("=" * 60)

    initialize_db()
    
    # 1. Run engine
    result = query_engine_run(question)
    
    if "error" in result:
        print(f"\n❌ Error: {result['error']}")
        if "sql" in result:
            print(f"\n  Attempted SQL: {result['sql']}")
        print("=" * 60)
        return

    sql = result.get("sql", "")
    data = result.get("raw_results", [])
    summary = result.get("summary", "")

    # 2. Show SQL (transparency)
    print(f"\n  [SQL Executed]: {sql}")
    
    # 3. Show raw data table
    if not data:
        print("\n  ℹ️  No matching reviews found in the database.")
    else:
        # Prevent massive terminal dumps, show first 10
        display_data = data[:10]
        columns = list(display_data[0].keys())
        widths = {col: max(len(str(col)), *(len(str(r.get(col, ""))) for r in display_data)) for col in columns}
        # Cap max column width to keep it readable
        widths = {c: min(w, 50) for c, w in widths.items()}

        header = " | ".join(col.ljust(widths[col]) for col in columns)
        separator = "-+-".join("-" * widths[col] for col in columns)
        
        print("\n  [Raw Data (Limit 10)]:")
        print(f"  {header}")
        print(f"  {separator}")
        for row in display_data:
            line_parts = []
            for col in columns:
                val = str(row.get(col, "")).replace("\n", " ")
                if len(val) > widths[col]:
                    val = val[:widths[col]-3] + "..."
                line_parts.append(val.ljust(widths[col]))
            print(f"  {' | '.join(line_parts)}")
        
        if len(data) > 10:
            print(f"  ... (+ {len(data)-10} more rows)")

    # 4. Show Molly's Insight
    print(f"\n  💡 Molly's Insight:\n")
    # Wrap text for readability
    import textwrap
    wrapped = textwrap.fill(summary, width=80, initial_indent="  ", subsequent_indent="  ")
    print(f"{wrapped}")

    print("\n" + "=" * 60)


# ---------------------------------------------------------------------------
# Command: --stats
# ---------------------------------------------------------------------------
def cmd_stats():
    """Print database summary statistics."""
    print("\n📊 VoC Database Statistics")
    print("=" * 60)

    initialize_db()
    stats = get_review_stats()

    print(f"\n  Total Reviews:    {stats['total_reviews']}")
    print(f"  Processed:        {stats['processed_count']}")
    print(f"  Unprocessed:      {stats['unprocessed_count']}")
    print(f"  Last Ingestion:   {stats['last_ingestion'] or 'Never'}")

    if stats["by_product"]:
        print("\n  By Product:")
        for pid, cnt in stats["by_product"].items():
            name = PRODUCTS.get(pid, {}).get("name", pid)
            print(f"    {name:25s}: {cnt}")

    if stats["by_source"]:
        print("\n  By Source:")
        for src, cnt in stats["by_source"].items():
            print(f"    {src:25s}: {cnt}")

    if stats["by_sentiment"]:
        total_sent = sum(stats["by_sentiment"].values())
        print("\n  By Sentiment:")
        for sent, cnt in sorted(stats["by_sentiment"].items()):
            pct = round(cnt / total_sent * 100) if total_sent else 0
            bar = "█" * (pct // 5)
            print(f"    {sent:25s}: {cnt:4d} ({pct:2d}%) {bar}")

    if stats["total_reviews"] == 0:
        print("\n  ℹ️  Database is empty. Run: python agent.py --ingest")

    print("\n" + "=" * 60)


# ---------------------------------------------------------------------------
# Command: --mock-ingest
# ---------------------------------------------------------------------------
def cmd_mock_ingest(count: int = 100):
    """Ingest mock reviews for testing without API keys."""
    print(f"\n🧪 Mock ingestion: generating {count} reviews per product…")
    print("=" * 60)

    initialize_db()
    delta_data = {}

    for product_id, product in PRODUCTS.items():
        product_name = product["name"]
        print(f"\n📦 Generating {count} mock reviews for {product_name}…")
        reviews = mock_scrape_reviews(product_id, count=count)
        result = store_reviews(reviews, product_id, "mock")
        new = result["new_count"]
        skip = result["skipped_count"]
        total = result["total_in_db"]
        delta_data[product_id] = {
            "new_reviews": new,
            "sources": {"mock_amazon": new // 2, "mock_flipkart": new - new // 2},
        }
        print(
            f"✅ {product_name}: {new} new, {skip} skipped, {total} total in DB"
        )
        log_ingestion_run(product_id, new, total)

    save_delta_log(delta_data)

    total_new = sum(d["new_reviews"] for d in delta_data.values())
    print("\n" + "=" * 60)
    print(f"🎉 Mock ingestion complete! {total_new} reviews added.")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Command: --mock-analyze
# ---------------------------------------------------------------------------
def cmd_mock_analyze():
    """Run mock analysis on unprocessed reviews (no API key needed)."""
    print("\n🧪 Mock analysis: classifying reviews by rating + keywords…")
    print("=" * 60)

    initialize_db()
    result = mock_analyze_reviews(product_id=None)

    print(f"\n📊 Mock Analysis Results:")
    print(f"   Processed: {result['processed_count']} reviews")

    if result["sentiment_breakdown"]:
        print("\n   Sentiment Breakdown:")
        for sent, count in sorted(result["sentiment_breakdown"].items()):
            pct = round(count / result["processed_count"] * 100) if result["processed_count"] else 0
            bar = "█" * (pct // 5)
            print(f"     {sent:10s}: {count:4d} ({pct}%) {bar}")

    if result["theme_breakdown"]:
        print("\n   Theme Breakdown (top 10):")
        for theme, count in list(result["theme_breakdown"].items())[:10]:
            print(f"     {theme:30s}: {count}")

    print("=" * 60)


# ---------------------------------------------------------------------------
# Command: --mock-pipeline (full mock run)
# ---------------------------------------------------------------------------
def cmd_mock_pipeline(count: int = 100):
    """Run full mock pipeline: mock-ingest → mock-analyze → report."""
    start = time.time()
    print("\n" + "🧪" * 30)
    print("  FULL MOCK PIPELINE (no API keys needed)")
    print("🧪" * 30)

    print("\n[Step 1/3] MOCK INGESTION")
    cmd_mock_ingest(count=count)

    print("\n[Step 2/3] MOCK ANALYSIS")
    cmd_mock_analyze()

    print("\n[Step 3/3] REPORTING")
    cmd_report()

    elapsed = round(time.time() - start, 1)
    print("\n" + "🧪" * 30)
    print(f"  MOCK PIPELINE COMPLETE — {elapsed}s elapsed")
    print("🧪" * 30)


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="🎧 VoC Intelligence Agent — Autonomous review analysis for Master Buds",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python agent.py --stats                     Show database statistics
  python agent.py --ingest                    Scrape reviews from Amazon/Flipkart  
  python agent.py --analyze                   Run LLM sentiment/theme analysis
  python agent.py --report                    Generate action reports
  python agent.py --pipeline                  Full run: ingest → analyze → report
  python agent.py --query "compare products"  Ask a question about the data
  python agent.py --query "top complaints"    Find most common issues
  python agent.py --query "battery issues"    Search by theme
        """,
    )

    parser.add_argument(
        "--ingest",
        action="store_true",
        help="Scrape new reviews from Amazon and Flipkart",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Run LLM sentiment and theme analysis on unprocessed reviews",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate global_actions.md and weekly_delta.md reports",
    )
    parser.add_argument(
        "--pipeline",
        action="store_true",
        help="Run full autonomous pipeline: ingest → analyze → report",
    )
    parser.add_argument(
        "--query",
        type=str,
        metavar="QUESTION",
        help='Ask a natural language question, e.g. "compare products"',
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print database summary statistics",
    )
    parser.add_argument(
        "--mock-ingest",
        action="store_true",
        help="Ingest mock reviews for testing (no API keys needed)",
    )
    parser.add_argument(
        "--mock-analyze",
        action="store_true",
        help="Run mock analysis using rating + keywords (no API keys needed)",
    )
    parser.add_argument(
        "--mock-pipeline",
        action="store_true",
        help="Full mock pipeline: mock-ingest → mock-analyze → report",
    )
    parser.add_argument(
        "--mock-count",
        type=int,
        default=100,
        help="Number of mock reviews per product (default: 100)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="Max review pages to scrape per product/source (default: 10)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Analysis batch size (default: 20)",
    )

    args = parser.parse_args()

    # Must specify at least one command
    has_cmd = any([
        args.ingest, args.analyze, args.report, args.pipeline,
        args.query, args.stats,
        args.mock_ingest, args.mock_analyze, args.mock_pipeline,
    ])
    if not has_cmd:
        parser.print_help()
        sys.exit(1)

    # Dispatch
    if args.mock_pipeline:
        cmd_mock_pipeline(count=args.mock_count)
    elif args.pipeline:
        cmd_pipeline(max_pages=args.max_pages, batch_size=args.batch_size)
    elif args.mock_ingest:
        cmd_mock_ingest(count=args.mock_count)
    elif args.ingest:
        cmd_ingest(max_pages=args.max_pages)
    elif args.mock_analyze:
        cmd_mock_analyze()
    elif args.analyze:
        cmd_analyze(batch_size=args.batch_size)
    elif args.report:
        cmd_report()
    elif args.query:
        cmd_query(args.query)
    elif args.stats:
        cmd_stats()


if __name__ == "__main__":
    main()
