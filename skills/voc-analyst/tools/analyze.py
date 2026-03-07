"""
VoC Intelligence Agent — Review Analyzer
Zero-shot sentiment classification and thematic tagging via Groq LLM.
"""

import os
import sys
import json
import time
import logging
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

# Ensure sibling modules are importable when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"
API_CALL_DELAY = 0.5  # seconds between API calls (rate-limit courtesy)

THEME_TAXONOMY = [
    "Sound Quality",
    "Battery Life",
    "Comfort & Fit",
    "ANC (Active Noise Cancellation)",
    "App Experience",
    "Price & Value",
    "Build Quality",
    "Delivery & Packaging",
    "Call Quality",
    "Connectivity (Bluetooth)",
    "Heat & Sweat Resistance",
]

FALLBACK_RESULT = {
    "sentiment": "Neutral",
    "themes": ["Sound Quality"],
    "confidence": 0.1,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Groq client
# ---------------------------------------------------------------------------

def _get_client() -> Groq:
    """Initialise and return a Groq client."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set. Please configure .env")
    return Groq(api_key=GROQ_API_KEY)


# ---------------------------------------------------------------------------
# Single-review analysis
# ---------------------------------------------------------------------------

def analyze_single_review(
    review_text: str,
    review_title: str = "",
    rating: int = 0,
) -> dict:
    """
    Classify a single review using Groq LLM.

    Args:
        review_text:  The full review body.
        review_title: The review headline/title.
        rating:       Star rating (1-5).

    Returns:
        {sentiment: str, themes: list[str], confidence: float}
    """
    themes_list = ", ".join(THEME_TAXONOMY)

    system_prompt = (
        "You are a review classification engine. "
        "Respond ONLY with valid JSON. No explanations."
    )

    user_prompt = (
        f"Analyze this product review and return JSON with exactly these fields:\n"
        f'{{\n'
        f'  "sentiment": "Positive" | "Negative" | "Neutral",\n'
        f'  "themes": [list of 1-3 themes from the allowed list only],\n'
        f'  "confidence": 0.0-1.0\n'
        f'}}\n\n'
        f"Allowed themes: {themes_list}\n\n"
        f"Rating: {rating}/5\n"
        f"Title: {review_title}\n"
        f"Review: {review_text[:500]}\n\n"
        f"Rules:\n"
        f'- sentiment must be exactly "Positive", "Negative", or "Neutral"\n'
        f"- themes must only contain values from the allowed list above\n"
        f"- If no theme clearly applies, use the single most relevant one"
    )

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            max_tokens=256,
        )

        raw = response.choices[0].message.content.strip()

        # Strip markdown code fences if the model wraps output
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]  # drop first ```json line
            raw = raw.rsplit("```", 1)[0]  # drop closing ```
            raw = raw.strip()

        result = json.loads(raw)

        # Validate and sanitise
        sentiment = result.get("sentiment", "Neutral")
        if sentiment not in ("Positive", "Negative", "Neutral"):
            sentiment = "Neutral"

        themes = result.get("themes", [])
        themes = [t for t in themes if t in THEME_TAXONOMY]
        if not themes:
            themes = ["Sound Quality"]

        confidence = float(result.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        return {
            "sentiment": sentiment,
            "themes": themes,
            "confidence": confidence,
        }

    except json.JSONDecodeError as exc:
        logger.warning("JSON parse error from Groq: %s", exc)
        return dict(FALLBACK_RESULT)

    except Exception as exc:
        logger.error("Groq API call failed: %s", exc)
        return dict(FALLBACK_RESULT)


# ---------------------------------------------------------------------------
# Batch analysis (main entry point for OpenClaw)
# ---------------------------------------------------------------------------

def analyze_reviews(
    product_id: str | None = None,
    batch_size: int = 20,
) -> dict:
    """
    Process unanalysed reviews through Groq LLM.

    Args:
        product_id: Optional filter by product.
        batch_size: Reviews per processing batch.

    Returns:
        {processed_count, sentiment_breakdown, theme_breakdown, product_id}
    """
    reviews = db.get_unprocessed_reviews(product_id, limit=batch_size * 5)
    total = len(reviews)

    if total == 0:
        logger.info("No unprocessed reviews to analyse.")
        return {
            "processed_count": 0,
            "sentiment_breakdown": {},
            "theme_breakdown": {},
            "product_id": product_id or "all",
        }

    logger.info(
        "Starting analysis of %d unprocessed reviews (product=%s)",
        total, product_id or "all",
    )

    sentiment_counts: dict[str, int] = {}
    theme_counts: dict[str, int] = {}
    processed = 0

    for i, review in enumerate(reviews, 1):
        result = analyze_single_review(
            review_text=review["text"],
            review_title=review.get("title", ""),
            rating=review.get("rating", 0),
        )

        # Persist to DB
        db.update_review_analysis(
            review_id=review["review_id"],
            sentiment=result["sentiment"],
            themes=result["themes"],
        )

        # Tally
        sentiment_counts[result["sentiment"]] = (
            sentiment_counts.get(result["sentiment"], 0) + 1
        )
        for theme in result["themes"]:
            theme_counts[theme] = theme_counts.get(theme, 0) + 1

        processed += 1

        if i % 10 == 0 or i == total:
            logger.info("Analysed %d/%d reviews…", i, total)

        # Rate-limit courtesy
        if i < total:
            time.sleep(API_CALL_DELAY)

    return {
        "processed_count": processed,
        "sentiment_breakdown": sentiment_counts,
        "theme_breakdown": dict(
            sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)
        ),
        "product_id": product_id or "all",
    }


# ---------------------------------------------------------------------------
# Efficient batch analysis (multiple reviews per API call)
# ---------------------------------------------------------------------------

def analyze_batch_efficient(reviews: list[dict], batch_size: int = 10) -> list[dict]:
    """
    Send multiple reviews in a single Groq API call for efficiency.
    Falls back to single-review mode if batch parsing fails.

    Args:
        reviews:    List of review dicts with keys: text, title, rating.
        batch_size: Max reviews per API call.

    Returns:
        List of {sentiment, themes, confidence} dicts in the same order as input.
    """
    themes_list = ", ".join(THEME_TAXONOMY)
    all_results: list[dict] = []

    for batch_start in range(0, len(reviews), batch_size):
        batch = reviews[batch_start : batch_start + batch_size]

        # Construct multi-review prompt
        review_lines = []
        for idx, r in enumerate(batch, 1):
            review_lines.append(
                f"Review {idx} (Rating: {r.get('rating', 0)}/5, "
                f"Title: {r.get('title', '')}):\n"
                f"{r.get('text', '')[:300]}"
            )

        system_prompt = (
            "You are a review classification engine. "
            "Respond ONLY with a valid JSON array. No explanations."
        )

        user_prompt = (
            f"Analyze each review below and return a JSON array where each element has:\n"
            f'{{\n'
            f'  "sentiment": "Positive" | "Negative" | "Neutral",\n'
            f'  "themes": [1-3 themes from allowed list],\n'
            f'  "confidence": 0.0-1.0\n'
            f'}}\n\n'
            f"Allowed themes: {themes_list}\n\n"
            + "\n\n".join(review_lines)
            + "\n\nReturn exactly one JSON object per review in the same order."
        )

        try:
            client = _get_client()
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                max_tokens=1024,
            )

            raw = response.choices[0].message.content.strip()

            # Strip markdown fences
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
                raw = raw.rsplit("```", 1)[0]
                raw = raw.strip()

            batch_results = json.loads(raw)

            if not isinstance(batch_results, list):
                raise ValueError("Expected JSON array")

            # Validate each result
            for res in batch_results:
                sentiment = res.get("sentiment", "Neutral")
                if sentiment not in ("Positive", "Negative", "Neutral"):
                    sentiment = "Neutral"
                themes = [t for t in res.get("themes", []) if t in THEME_TAXONOMY]
                if not themes:
                    themes = ["Sound Quality"]
                confidence = max(0.0, min(1.0, float(res.get("confidence", 0.5))))
                all_results.append({
                    "sentiment": sentiment,
                    "themes": themes,
                    "confidence": confidence,
                })

            # Pad if model returned fewer results than expected
            while len(all_results) < batch_start + len(batch):
                all_results.append(dict(FALLBACK_RESULT))

        except Exception as exc:
            logger.warning(
                "Batch analysis failed, falling back to single-review mode: %s", exc
            )
            for r in batch:
                result = analyze_single_review(
                    r.get("text", ""), r.get("title", ""), r.get("rating", 0)
                )
                all_results.append(result)
                time.sleep(API_CALL_DELAY)

        # Inter-batch delay
        time.sleep(API_CALL_DELAY)

    return all_results


# ---------------------------------------------------------------------------
# Mock Analyzer (for testing without Groq API key)
# ---------------------------------------------------------------------------

import random as _random

# Keyword → theme mapping for deterministic mock analysis
_KEYWORD_THEME_MAP = {
    "sound": "Sound Quality",
    "audio": "Sound Quality",
    "bass": "Sound Quality",
    "treble": "Sound Quality",
    "vocal": "Sound Quality",
    "driver": "Sound Quality",
    "battery": "Battery Life",
    "charge": "Battery Life",
    "hours": "Battery Life",
    "comfort": "Comfort & Fit",
    "fit": "Comfort & Fit",
    "ear": "Comfort & Fit",
    "anc": "ANC (Active Noise Cancellation)",
    "noise cancel": "ANC (Active Noise Cancellation)",
    "noise": "ANC (Active Noise Cancellation)",
    "app": "App Experience",
    "eq": "App Experience",
    "price": "Price & Value",
    "value": "Price & Value",
    "money": "Price & Value",
    "worth": "Price & Value",
    "build": "Build Quality",
    "plastic": "Build Quality",
    "quality": "Build Quality",
    "delivery": "Delivery & Packaging",
    "packaging": "Delivery & Packaging",
    "call": "Call Quality",
    "mic": "Call Quality",
    "microphone": "Call Quality",
    "bluetooth": "Connectivity (Bluetooth)",
    "connect": "Connectivity (Bluetooth)",
    "disconnect": "Connectivity (Bluetooth)",
    "pair": "Connectivity (Bluetooth)",
    "sweat": "Heat & Sweat Resistance",
    "gym": "Heat & Sweat Resistance",
    "workout": "Heat & Sweat Resistance",
    "water": "Heat & Sweat Resistance",
}


def mock_analyze_single(review_text: str, review_title: str, rating: int) -> dict:
    """Deterministic mock analysis based on rating and keyword matching."""
    # Sentiment from rating
    if rating >= 4:
        sentiment = "Positive"
    elif rating <= 2:
        sentiment = "Negative"
    else:
        sentiment = "Neutral"

    # Themes from keyword matching
    combined = (review_text + " " + review_title).lower()
    matched_themes = set()
    for keyword, theme in _KEYWORD_THEME_MAP.items():
        if keyword in combined:
            matched_themes.add(theme)

    themes = list(matched_themes)[:3]
    if not themes:
        themes = [_random.choice(THEME_TAXONOMY)]

    return {
        "sentiment": sentiment,
        "themes": themes,
        "confidence": 0.85 if rating in (1, 5) else 0.65,
    }


def mock_analyze_reviews(product_id: str | None = None) -> dict:
    """
    Mock analysis — classify all unprocessed reviews using rating + keywords.
    No API calls needed.
    """
    reviews = db.get_unprocessed_reviews(product_id, limit=1000)
    total = len(reviews)

    if total == 0:
        logger.info("No unprocessed reviews to analyse (mock).")
        return {
            "processed_count": 0,
            "sentiment_breakdown": {},
            "theme_breakdown": {},
            "product_id": product_id or "all",
        }

    logger.info("Mock analysing %d reviews…", total)

    sentiment_counts: dict[str, int] = {}
    theme_counts: dict[str, int] = {}

    for i, review in enumerate(reviews, 1):
        result = mock_analyze_single(
            review["text"], review.get("title", ""), review.get("rating", 0)
        )
        db.update_review_analysis(
            review_id=review["review_id"],
            sentiment=result["sentiment"],
            themes=result["themes"],
        )
        sentiment_counts[result["sentiment"]] = (
            sentiment_counts.get(result["sentiment"], 0) + 1
        )
        for theme in result["themes"]:
            theme_counts[theme] = theme_counts.get(theme, 0) + 1

        if i % 50 == 0 or i == total:
            logger.info("Mock analysed %d/%d reviews…", i, total)

    return {
        "processed_count": total,
        "sentiment_breakdown": sentiment_counts,
        "theme_breakdown": dict(
            sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)
        ),
        "product_id": product_id or "all",
    }


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  VoC Analyzer — Self-test")
    print("=" * 60)

    test_reviews = [
        {
            "title": "Absolutely love these!",
            "text": "Best earbuds I've owned. The bass is incredible and battery "
                    "lasts a solid 8 hours. Comfortable fit even during workouts.",
            "rating": 5,
        },
        {
            "title": "Terrible bluetooth",
            "text": "Bluetooth disconnects every 5 minutes. Audio lag during calls. "
                    "Tried resetting multiple times. Waste of money at this price.",
            "rating": 1,
        },
        {
            "title": "Decent for the price",
            "text": "Average sound quality. Nothing special but nothing terrible. "
                    "ANC is basic but works on a bus. Build feels a bit plasticky.",
            "rating": 3,
        },
    ]

    if not GROQ_API_KEY:
        print("\n⚠️  GROQ_API_KEY not set — running syntax check only.")
        print("Module loaded successfully ✅")
        print(f"Theme taxonomy: {len(THEME_TAXONOMY)} themes")
        print(f"Model: {GROQ_MODEL}")
    else:
        for i, review in enumerate(test_reviews, 1):
            print(f"\n--- Review {i}: \"{review['title']}\" ---")
            result = analyze_single_review(
                review["text"], review["title"], review["rating"]
            )
            print(json.dumps(result, indent=2))
            if i < len(test_reviews):
                time.sleep(API_CALL_DELAY)

        print("\n✅ Analysis test complete!")
