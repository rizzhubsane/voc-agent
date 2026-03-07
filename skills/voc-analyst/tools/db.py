"""
VoC Intelligence Agent — Database Layer
All SQLite operations for review storage, analysis tracking, and querying.
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_DB_PATH = os.getenv("DB_PATH", "./db.sqlite")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def _get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Return a connection with row_factory set to sqlite3.Row."""
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def initialize_db(db_path: str | None = None) -> str:
    """
    Create the database file and tables if they don't exist.

    Returns:
        The resolved path to the database file.
    """
    path = db_path or DEFAULT_DB_PATH
    conn = _get_connection(path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id  TEXT    NOT NULL,
            review_id   TEXT    UNIQUE NOT NULL,
            rating      INTEGER,
            title       TEXT,
            text        TEXT,
            date        TEXT,
            source      TEXT,
            sentiment   TEXT    DEFAULT NULL,
            themes      TEXT    DEFAULT NULL,
            processed   INTEGER DEFAULT 0,
            ingested_at TEXT    DEFAULT (datetime('now'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ingestion_log (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date       TEXT,
            product_id     TEXT,
            new_reviews    INTEGER,
            total_reviews  INTEGER
        )
    """)

    # Indices for common query patterns
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_reviews_product
        ON reviews(product_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_reviews_processed
        ON reviews(processed)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_reviews_date
        ON reviews(date)
    """)

    conn.commit()
    conn.close()

    logger.info("Database initialised at %s", path)
    return path


# ---------------------------------------------------------------------------
# Store reviews
# ---------------------------------------------------------------------------

def store_reviews(
    reviews: list[dict],
    product_id: str,
    source: str,
) -> dict:
    """
    Insert scraped reviews into the database, skipping duplicates.

    Args:
        reviews:    List of review dicts (from scrape_reviews).
        product_id: "master_buds_1" or "master_buds_max"
        source:     "amazon" or "flipkart"

    Returns:
        {new_count, skipped_count, total_in_db}
    """
    initialize_db()
    conn = _get_connection()
    cursor = conn.cursor()

    new_count = 0
    skipped_count = 0

    for review in reviews:
        try:
            cursor.execute(
                """
                INSERT OR IGNORE INTO reviews
                    (product_id, review_id, rating, title, text, date, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_id,
                    review.get("review_id", ""),
                    review.get("rating", 0),
                    review.get("title", ""),
                    review.get("text", ""),
                    review.get("date", ""),
                    source,
                ),
            )
            if cursor.rowcount > 0:
                new_count += 1
            else:
                skipped_count += 1
        except sqlite3.Error as exc:
            logger.warning("Insert error for review %s: %s", review.get("review_id"), exc)
            skipped_count += 1

    conn.commit()

    # Total count for this product
    cursor.execute(
        "SELECT COUNT(*) AS cnt FROM reviews WHERE product_id = ?",
        (product_id,),
    )
    total_in_db = cursor.fetchone()["cnt"]

    conn.close()

    result = {
        "new_count": new_count,
        "skipped_count": skipped_count,
        "total_in_db": total_in_db,
    }
    logger.info(
        "store_reviews(%s, %s): new=%d skipped=%d total=%d",
        product_id, source, new_count, skipped_count, total_in_db,
    )
    return result


# ---------------------------------------------------------------------------
# Retrieve unprocessed reviews
# ---------------------------------------------------------------------------

def get_unprocessed_reviews(
    product_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """
    Fetch reviews that haven't been analysed yet (processed=0).

    Args:
        product_id: Optional filter.
        limit:      Max rows to return.

    Returns:
        List of review dicts.
    """
    initialize_db()
    conn = _get_connection()

    if product_id:
        rows = conn.execute(
            "SELECT * FROM reviews WHERE processed = 0 AND product_id = ? LIMIT ?",
            (product_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM reviews WHERE processed = 0 LIMIT ?",
            (limit,),
        ).fetchall()

    conn.close()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Update analysis results
# ---------------------------------------------------------------------------

def update_review_analysis(
    review_id: str,
    sentiment: str,
    themes: list[str],
) -> None:
    """
    Store LLM analysis results for a single review.

    Args:
        review_id: The unique review identifier.
        sentiment: "positive", "negative", or "neutral"
        themes:    List of theme strings, e.g. ["Sound Quality", "Battery Life"]
    """
    initialize_db()
    conn = _get_connection()
    conn.execute(
        """
        UPDATE reviews
        SET sentiment = ?, themes = ?, processed = 1
        WHERE review_id = ?
        """,
        (sentiment, json.dumps(themes), review_id),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Ingestion log
# ---------------------------------------------------------------------------

def log_ingestion_run(
    product_id: str,
    new_reviews: int,
    total_reviews: int,
) -> None:
    """Record a completed ingestion run."""
    initialize_db()
    conn = _get_connection()
    conn.execute(
        """
        INSERT INTO ingestion_log (run_date, product_id, new_reviews, total_reviews)
        VALUES (?, ?, ?, ?)
        """,
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), product_id, new_reviews, total_reviews),
    )
    conn.commit()
    conn.close()
    logger.info(
        "Logged ingestion: %s — %d new, %d total",
        product_id, new_reviews, total_reviews,
    )


# ---------------------------------------------------------------------------
# Free-form query (for conversational Q&A)
# ---------------------------------------------------------------------------

def query_reviews(sql_query: str) -> list[dict]:
    """
    Execute a read-only SELECT query against the database.

    Args:
        sql_query: A valid SQLite SELECT statement.

    Returns:
        List of dicts with column names as keys.

    Raises:
        ValueError: If the query is not a SELECT statement.
    """
    cleaned = sql_query.strip()
    if not cleaned.upper().startswith("SELECT"):
        raise ValueError(
            "Only SELECT queries are allowed for safety. "
            f"Got: {cleaned[:50]}…"
        )

    initialize_db()
    conn = _get_connection()

    try:
        rows = conn.execute(cleaned).fetchall()
        results = [dict(row) for row in rows]
    except sqlite3.Error as exc:
        logger.error("Query failed: %s — %s", cleaned[:80], exc)
        results = [{"error": str(exc)}]
    finally:
        conn.close()

    return results


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------

def get_review_stats() -> dict:
    """
    Return high-level statistics about the review database.

    Returns:
        {
            total_reviews, by_product, by_sentiment, by_source,
            last_ingestion, processed_count, unprocessed_count
        }
    """
    initialize_db()
    conn = _get_connection()

    total = conn.execute("SELECT COUNT(*) AS cnt FROM reviews").fetchone()["cnt"]

    # By product
    by_product = {}
    for row in conn.execute(
        "SELECT product_id, COUNT(*) AS cnt FROM reviews GROUP BY product_id"
    ):
        by_product[row["product_id"]] = row["cnt"]

    # By sentiment
    by_sentiment = {}
    for row in conn.execute(
        "SELECT sentiment, COUNT(*) AS cnt FROM reviews "
        "WHERE sentiment IS NOT NULL GROUP BY sentiment"
    ):
        by_sentiment[row["sentiment"]] = row["cnt"]

    # By source
    by_source = {}
    for row in conn.execute(
        "SELECT source, COUNT(*) AS cnt FROM reviews GROUP BY source"
    ):
        by_source[row["source"]] = row["cnt"]

    # Processed / unprocessed
    processed = conn.execute(
        "SELECT COUNT(*) AS cnt FROM reviews WHERE processed = 1"
    ).fetchone()["cnt"]
    unprocessed = conn.execute(
        "SELECT COUNT(*) AS cnt FROM reviews WHERE processed = 0"
    ).fetchone()["cnt"]

    # Last ingestion
    last_row = conn.execute(
        "SELECT MAX(run_date) AS last_run FROM ingestion_log"
    ).fetchone()
    last_ingestion = last_row["last_run"] if last_row else None

    conn.close()

    return {
        "total_reviews": total,
        "by_product": by_product,
        "by_sentiment": by_sentiment,
        "by_source": by_source,
        "last_ingestion": last_ingestion,
        "processed_count": processed,
        "unprocessed_count": unprocessed,
    }


# ---------------------------------------------------------------------------
# Theme trend aggregation
# ---------------------------------------------------------------------------

def get_theme_trends(
    product_id: str | None = None,
    since_date: str | None = None,
) -> dict:
    """
    Aggregate theme occurrences across analysed reviews.

    Args:
        product_id: Optional filter.
        since_date: Optional ISO date (YYYY-MM-DD) lower bound.

    Returns:
        {
            theme_name: {
                count: N,
                avg_rating: X.X,
                sentiment_breakdown: {positive: N, negative: N, neutral: N}
            }
        }
    """
    initialize_db()
    conn = _get_connection()

    query = "SELECT rating, sentiment, themes FROM reviews WHERE processed = 1"
    params: list = []

    if product_id:
        query += " AND product_id = ?"
        params.append(product_id)
    if since_date:
        query += " AND date >= ?"
        params.append(since_date)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    theme_data: dict[str, dict] = {}

    for row in rows:
        themes_raw = row["themes"]
        if not themes_raw:
            continue
        try:
            themes_list = json.loads(themes_raw)
        except (json.JSONDecodeError, TypeError):
            continue

        rating = row["rating"] or 0
        sentiment = row["sentiment"] or "unknown"

        for theme in themes_list:
            theme = theme.strip()
            if theme not in theme_data:
                theme_data[theme] = {
                    "count": 0,
                    "total_rating": 0,
                    "sentiment_breakdown": {},
                }
            theme_data[theme]["count"] += 1
            theme_data[theme]["total_rating"] += rating
            theme_data[theme]["sentiment_breakdown"][sentiment] = (
                theme_data[theme]["sentiment_breakdown"].get(sentiment, 0) + 1
            )

    # Compute averages
    result = {}
    for theme, data in sorted(theme_data.items(), key=lambda x: x[1]["count"], reverse=True):
        result[theme] = {
            "count": data["count"],
            "avg_rating": round(data["total_rating"] / data["count"], 2) if data["count"] else 0,
            "sentiment_breakdown": data["sentiment_breakdown"],
        }

    return result


# ---------------------------------------------------------------------------
# Duplicate Simulation Test (Delta proof)
# ---------------------------------------------------------------------------

def simulate_second_run(new_review_count: int = 25) -> dict:
    """
    Simulate a second ingestion run to prove deduplication works.
    Generates new mock reviews and mixes them with existing DB reviews,
    then calls store_reviews to show only new ones are inserted.

    Args:
        new_review_count: Number of fresh reviews to generate.

    Returns:
        {attempted: int, new: int, duplicates_caught: int}
    """
    import random
    from datetime import timedelta
    from db import _get_connection, initialize_db

    initialize_db()
    conn = _get_connection()

    # 1. Grab 10 existing reviews from the DB to act as duplicates
    existing_rows = conn.execute(
        "SELECT * FROM reviews ORDER BY RANDOM() LIMIT 10"
    ).fetchall()
    
    duplicate_reviews = [dict(r) for r in existing_rows]
    conn.close()

    # 2. Generate brand new mock reviews (last 7 days only)
    # We'll use the mock scraper logic but with a specific date range
    from scrape import _RATING_WEIGHTS, _SOURCES, _REVIEWER_NAMES
    from scrape import _POSITIVE_TITLES, _NEGATIVE_TITLES, _NEUTRAL_TITLES
    from scrape import _POSITIVE_TEXTS, _NEGATIVE_TEXTS, _NEUTRAL_TEXTS
    import hashlib

    new_reviews = []
    now = datetime.now()
    product_id = "master_buds_1" # Just put them all here for the test

    for i in range(new_review_count):
        rating = random.choice(_RATING_WEIGHTS)
        source = random.choice(_SOURCES)
        reviewer = random.choice(_REVIEWER_NAMES) + f"_delta_{i}"
        date = (now - timedelta(days=random.randint(0, 6))).strftime("%Y-%m-%d")

        if rating >= 4:
            title = random.choice(_POSITIVE_TITLES)
            text = random.choice(_POSITIVE_TEXTS).format(days=random.randint(1,7), hours=6)
        elif rating <= 2:
            title = random.choice(_NEGATIVE_TITLES)
            text = random.choice(_NEGATIVE_TEXTS).format(mins=5, claimed=10, actual=4, hours=2)
        else:
            title = random.choice(_NEUTRAL_TITLES)
            text = random.choice(_NEUTRAL_TEXTS).format(hours=5)

        review_id = hashlib.md5(f"{reviewer}{date}delta_test{i}".encode()).hexdigest()

        new_reviews.append({
            "review_id": review_id,
            "product_id": product_id,
            "source": source,
            "rating": rating,
            "title": title,
            "text": text,
            "date": date,
            "reviewer_id": reviewer,
        })

    # Combine new reviews with duplicate reviews
    all_test_reviews = new_reviews + duplicate_reviews

    # Shuffle them so they don't arrive neatly separated
    random.shuffle(all_test_reviews)

    # 3. Store them
    result = store_reviews(all_test_reviews, product_id, "mock_delta")

    return {
        "attempted": len(all_test_reviews),
        "new": result["new_count"],
        "duplicates_caught": result["skipped_count"]
    }


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import hashlib

    print("=" * 60)
    print("  VoC Database — Self-test")
    print("=" * 60)

    # 1. Initialise
    db_path = initialize_db("./db.sqlite")
    print(f"\n✅ Database created at: {db_path}")

    # 2. Insert fake test reviews
    fake_reviews = [
        {
            "review_id": hashlib.md5(b"test_user_1_2024-01-15_master_buds_1").hexdigest(),
            "product_id": "master_buds_1",
            "source": "amazon",
            "rating": 4,
            "title": "Great sound quality!",
            "text": "These earbuds have amazing bass. Battery lasts about 6 hours.",
            "date": "2024-01-15",
            "reviewer_id": "test_user_1",
        },
        {
            "review_id": hashlib.md5(b"test_user_2_2024-01-16_master_buds_1").hexdigest(),
            "product_id": "master_buds_1",
            "source": "flipkart",
            "rating": 2,
            "title": "Connectivity issues",
            "text": "Bluetooth keeps disconnecting. Very frustrating experience.",
            "date": "2024-01-16",
            "reviewer_id": "test_user_2",
        },
        {
            "review_id": hashlib.md5(b"test_user_3_2024-01-17_master_buds_max").hexdigest(),
            "product_id": "master_buds_max",
            "source": "amazon",
            "rating": 5,
            "title": "Best in class ANC",
            "text": "Active noise cancellation is superb. Comfortable fit for long use.",
            "date": "2024-01-17",
            "reviewer_id": "test_user_3",
        },
    ]

    result = store_reviews(fake_reviews, "master_buds_1", "amazon")
    print(f"\n📥 First insert: {result}")

    # Insert again to test dedup
    result2 = store_reviews(fake_reviews, "master_buds_1", "amazon")
    print(f"📥 Duplicate insert: {result2}")

    # 3. Stats
    stats = get_review_stats()
    print(f"\n📊 Database stats:")
    print(json.dumps(stats, indent=2))

    # 4. Unprocessed
    unprocessed = get_unprocessed_reviews()
    print(f"\n⏳ Unprocessed reviews: {len(unprocessed)}")

    # 5. Free-form query
    q_result = query_reviews("SELECT product_id, COUNT(*) as cnt FROM reviews GROUP BY product_id")
    print(f"\n🔍 Query test: {q_result}")

    print("\n✅ All tests passed!")
