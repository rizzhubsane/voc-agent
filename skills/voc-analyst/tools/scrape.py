"""
VoC Intelligence Agent — Review Scraper
Scrapes public Amazon and Flipkart product reviews using ScraperAPI.
"""

import os
import re
import json
import time
import hashlib
import logging
from datetime import datetime
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")
SCRAPER_API_BASE = "https://api.scraperapi.com"
REQUEST_TIMEOUT = 60  # seconds
RETRY_DELAY = 5       # seconds before retry on 429
PAGE_DELAY = 2         # seconds between pages (respectful crawling)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scraperapi_get(url: str, render: bool = True) -> requests.Response | None:
    """Fetch a URL through ScraperAPI with one retry on 429."""
    params = {
        "api_key": SCRAPER_API_KEY,
        "url": url,
    }
    if render:
        params["render"] = "true"

    for attempt in range(2):  # max 2 attempts
        try:
            resp = requests.get(
                SCRAPER_API_BASE,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 429:
                logger.warning("Rate limited (429). Retrying in %ds…", RETRY_DELAY)
                time.sleep(RETRY_DELAY)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            logger.error("Request failed (attempt %d): %s", attempt + 1, exc)
            if attempt == 0:
                time.sleep(RETRY_DELAY)
    return None


def _parse_date(raw_date: str) -> str:
    """
    Best-effort date parse → YYYY-MM-DD.
    Handles formats like:
      - 'Reviewed in India on 5 March 2024'
      - '5 March 2024'
      - 'Mar 05, 2024'
    Returns original string if parsing fails.
    """
    # Strip common prefixes
    cleaned = re.sub(r"Reviewed in \w+ on\s*", "", raw_date).strip()
    cleaned = re.sub(r"Certified Buyer,?\s*", "", cleaned).strip()

    date_formats = [
        "%d %B %Y",      # 5 March 2024
        "%d %b %Y",      # 5 Mar 2024
        "%B %d, %Y",     # March 5, 2024
        "%b %d, %Y",     # Mar 05, 2024
        "%d-%m-%Y",      # 05-03-2024
        "%d/%m/%Y",      # 05/03/2024
        "%b, %Y",        # Mar, 2024  (Flipkart sometimes)
        "%B, %Y",        # March, 2024
    ]
    for fmt in date_formats:
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    logger.debug("Could not parse date: '%s'", raw_date)
    return raw_date


# ---------------------------------------------------------------------------
# Amazon Scraper
# ---------------------------------------------------------------------------

def scrape_amazon_reviews(product_url: str, max_pages: int = 10) -> list[dict]:
    """
    Scrape reviews from an Amazon India product page.

    Args:
        product_url: The Amazon product reviews URL (or product page URL).
        max_pages:   Number of review pages to scrape.

    Returns:
        List of review dicts with keys: rating, title, text, date, reviewer_id
    """
    all_reviews: list[dict] = []

    # Try to build a reviews-page URL from the base product URL
    # If it already contains 'product-reviews', use as-is
    if "product-reviews" not in product_url:
        # Extract ASIN from /dp/ASIN pattern
        asin_match = re.search(r"/dp/([A-Z0-9]{10})", product_url)
        if asin_match:
            asin = asin_match.group(1)
            base_reviews_url = (
                f"https://www.amazon.in/product-reviews/{asin}"
                f"/ref=cm_cr_arp_d_paging_btm_next_{{page}}"
                f"?ie=UTF8&reviewerType=all_reviews&pageNumber={{page}}"
            )
        else:
            logger.error("Cannot extract ASIN from URL: %s", product_url)
            return []
    else:
        # Already a reviews URL — inject page placeholder
        base_reviews_url = re.sub(
            r"pageNumber=\d+", "pageNumber={page}", product_url
        )
        if "pageNumber=" not in base_reviews_url:
            sep = "&" if "?" in base_reviews_url else "?"
            base_reviews_url += f"{sep}pageNumber={{page}}"

    for page in range(1, max_pages + 1):
        page_url = base_reviews_url.format(page=page)
        logger.info("Amazon page %d/%d: %s", page, max_pages, page_url[:120])

        resp = _scraperapi_get(page_url)
        if resp is None:
            logger.warning("Skipping page %d — request failed", page)
            continue

        soup = BeautifulSoup(resp.text, "lxml")
        review_divs = soup.find_all("div", attrs={"data-hook": "review"})

        if not review_divs:
            logger.info("No reviews found on page %d — stopping.", page)
            break

        for div in review_divs:
            try:
                # Rating
                star_el = div.find("i", attrs={"data-hook": "review-star-rating"})
                if star_el:
                    star_text = star_el.get_text(strip=True)
                    rating = int(float(star_text.split(" ")[0]))
                else:
                    rating = 0

                # Title
                title_el = div.find("a", attrs={"data-hook": "review-title"})
                if not title_el:
                    title_el = div.find("span", attrs={"data-hook": "review-title"})
                title = title_el.get_text(strip=True) if title_el else ""
                # Amazon sometimes prepends "X.0 out of 5 stars" in the title span
                title = re.sub(r"^\d+\.?\d*\s+out of \d+ stars\s*", "", title)

                # Review body
                body_el = div.find("span", attrs={"data-hook": "review-body"})
                text = body_el.get_text(strip=True) if body_el else ""

                # Date
                date_el = div.find("span", attrs={"data-hook": "review-date"})
                raw_date = date_el.get_text(strip=True) if date_el else ""
                date = _parse_date(raw_date)

                # Reviewer ID (profile link)
                profile_el = div.find("a", class_=re.compile("author"))
                if profile_el and profile_el.get("href"):
                    reviewer_id = profile_el["href"].split("/")[-1].split("?")[0]
                else:
                    profile_el = div.find("span", class_="a-profile-name")
                    reviewer_id = (
                        profile_el.get_text(strip=True) if profile_el else "anonymous"
                    )

                if text:  # only keep reviews with actual body text
                    all_reviews.append({
                        "rating": rating,
                        "title": title,
                        "text": text,
                        "date": date,
                        "reviewer_id": reviewer_id,
                    })

            except Exception as exc:
                logger.debug("Error parsing a review div: %s", exc)
                continue

        logger.info(
            "Page %d: found %d reviews (total so far: %d)",
            page, len(review_divs), len(all_reviews),
        )
        if page < max_pages:
            time.sleep(PAGE_DELAY)

    return all_reviews


# ---------------------------------------------------------------------------
# Flipkart Scraper
# ---------------------------------------------------------------------------

def scrape_flipkart_reviews(product_url: str, max_pages: int = 10) -> list[dict]:
    """
    Scrape reviews from a Flipkart product page.

    Args:
        product_url: The Flipkart product/reviews URL.
        max_pages:   Number of review pages to scrape.

    Returns:
        List of review dicts with keys: rating, title, text, date, reviewer_id
    """
    all_reviews: list[dict] = []

    # Build paginated URL
    base_url = product_url.split("?")[0]

    for page in range(1, max_pages + 1):
        page_url = f"{base_url}?page={page}"
        logger.info("Flipkart page %d/%d: %s", page, max_pages, page_url[:120])

        resp = _scraperapi_get(page_url)
        if resp is None:
            logger.warning("Skipping page %d — request failed", page)
            continue

        soup = BeautifulSoup(resp.text, "lxml")

        # Flipkart review containers — try multiple known class selectors
        review_containers = soup.find_all("div", class_="RcXBOT")
        if not review_containers:
            review_containers = soup.find_all("div", class_="col _2wzgFH K0kLPL")
        if not review_containers:
            # Fallback: look for review blocks by structural pattern
            review_containers = soup.find_all("div", class_=re.compile(r"EKFha-"))

        if not review_containers:
            logger.info("No reviews found on page %d — stopping.", page)
            break

        for container in review_containers:
            try:
                # Rating — look for the rating div
                rating_el = container.find("div", class_=re.compile(r"_1lRcqv|XQDdHH|hGQGAP"))
                if rating_el:
                    rating_text = rating_el.get_text(strip=True)
                    rating = int(float(rating_text))
                else:
                    rating = 0

                # Title
                title_el = container.find("p", class_=re.compile(r"z9E0IG|_2-N8zT"))
                title = title_el.get_text(strip=True) if title_el else ""

                # Review body
                body_el = container.find("div", class_=re.compile(r"ZmyHeo|t-ZTKy"))
                if body_el:
                    # Remove "READ MORE" spans
                    for span in body_el.find_all("span", class_=re.compile(r"teGi1e")):
                        span.decompose()
                    text = body_el.get_text(strip=True)
                else:
                    text = ""

                # Date
                date_el = container.find("p", class_=re.compile(r"_2sc7ZR|_2mcZGG"))
                raw_date = date_el.get_text(strip=True) if date_el else ""
                date = _parse_date(raw_date)

                # Reviewer name (used as proxy ID)
                reviewer_el = container.find("p", class_=re.compile(r"_2sc7ZR|_2V5EHH"))
                if not reviewer_el:
                    reviewer_el = container.find("p", class_=re.compile(r"MrFlB3"))
                reviewer_id = (
                    reviewer_el.get_text(strip=True) if reviewer_el else "anonymous"
                )

                if text:
                    all_reviews.append({
                        "rating": rating,
                        "title": title,
                        "text": text,
                        "date": date,
                        "reviewer_id": reviewer_id,
                    })

            except Exception as exc:
                logger.debug("Error parsing a Flipkart review: %s", exc)
                continue

        logger.info(
            "Page %d: found %d reviews (total so far: %d)",
            page, len(review_containers), len(all_reviews),
        )
        if page < max_pages:
            time.sleep(PAGE_DELAY)

    return all_reviews


# ---------------------------------------------------------------------------
# Main Entry Point (called by OpenClaw)
# ---------------------------------------------------------------------------

def scrape_reviews(
    product_id: str,
    source: str,
    url: str,
    max_pages: int = 10,
) -> list[dict]:
    """
    Main entry point for OpenClaw skill.

    Args:
        product_id: "master_buds_1" or "master_buds_max"
        source:     "amazon" or "flipkart"
        url:        Full product reviews URL
        max_pages:  Number of review pages to scrape

    Returns:
        List of review dicts enriched with product_id, source, and review_id.
    """
    logger.info(
        "Starting scrape: product=%s source=%s max_pages=%d",
        product_id, source, max_pages,
    )
    logger.info("URL: %s", url)

    if not SCRAPER_API_KEY:
        logger.error("SCRAPER_API_KEY not set. Please configure .env")
        return []

    if not url:
        logger.error("No URL provided for %s / %s", product_id, source)
        return []

    # Dispatch to platform-specific scraper
    if source.lower() == "amazon":
        raw_reviews = scrape_amazon_reviews(url, max_pages)
    elif source.lower() == "flipkart":
        raw_reviews = scrape_flipkart_reviews(url, max_pages)
    else:
        logger.error("Unknown source '%s'. Use 'amazon' or 'flipkart'.", source)
        return []

    # Enrich each review with metadata and generate unique review_id
    enriched = []
    for review in raw_reviews:
        review_id = hashlib.md5(
            f"{review['reviewer_id']}{review['date']}{product_id}".encode()
        ).hexdigest()

        enriched.append({
            "review_id": review_id,
            "product_id": product_id,
            "source": source.lower(),
            "rating": review["rating"],
            "title": review["title"],
            "text": review["text"],
            "date": review["date"],
            "reviewer_id": review["reviewer_id"],
        })

    logger.info(
        "Scrape complete: %d reviews for %s from %s",
        len(enriched), product_id, source,
    )
    return enriched


# ---------------------------------------------------------------------------
# Mock Scraper (for testing without API keys)
# ---------------------------------------------------------------------------

import random
from datetime import timedelta as _td

_POSITIVE_TITLES = [
    "Amazing sound quality!", "Best earbuds under 2000!",
    "Great battery life", "Love the bass!", "Perfect for workouts",
    "Exceeded expectations", "Best purchase this year",
    "Crystal clear audio", "Comfortable fit all day",
    "Value for money!", "Superb noise cancellation",
    "Premium feel at budget price", "Daily driver material",
]
_NEGATIVE_TITLES = [
    "Bluetooth keeps disconnecting", "Battery drains fast",
    "Uncomfortable after 30 mins", "ANC is disappointing",
    "Broke after 2 weeks", "Not worth the hype",
    "Call quality is terrible", "Audio lag in games",
    "One earbud stopped working", "Cheap build quality",
    "Ear tips don't fit well", "Charging case stopped working",
]
_NEUTRAL_TITLES = [
    "Decent for the price", "Average sound, nothing special",
    "OK for casual listening", "It's fine, I guess",
    "Gets the job done", "Mixed feelings about this one",
]

_POSITIVE_TEXTS = [
    "I've been using these for {days} days and the sound quality is phenomenal. The bass is deep without being muddy, and vocals come through crystal clear. Battery easily lasts {hours} hours on a single charge. Highly recommend!",
    "For the price, these earbuds are unbeatable. The ANC works surprisingly well on my daily metro commute. The touch controls are responsive and the fit is comfortable even for long listening sessions.",
    "Best earbuds I've owned in this price range. The 13mm drivers deliver punchy bass that rivals earbuds twice the price. Bluetooth 5.1 connection has been rock solid — no dropouts at all.",
    "Bought these for gym use and they're perfect. Sweat-resistant, secure fit, and the sound keeps me motivated. Call quality is also decent when I need to take calls mid-workout.",
    "The app integration is fantastic. EQ customization lets me tune the sound exactly how I like it. Battery case gives me nearly a full week without needing to charge. Great product!",
]
_NEGATIVE_TEXTS = [
    "Very disappointed. Bluetooth disconnects every {mins} minutes when my phone is in my pocket. Tried resetting multiple times. At this price I expected better connectivity.",
    "The ANC is basically non-existent. Can still hear everything around me. Also the ear tips are uncomfortable — my ears hurt after just 30 minutes of use. Returning these.",
    "Battery life is nowhere near what they advertise. They claim {claimed}h but I barely get {actual}h. Also one earbud is noticeably quieter than the other. Quality control issues.",
    "Call quality is terrible. People on the other end say I sound muffled and distant. Mic picks up way too much background noise. Not suitable for work calls at all.",
    "Build quality feels very cheap and plasticky. The charging case lid is already loose after 2 weeks. The glossy finish scratches just by looking at it. Save your money.",
]
_NEUTRAL_TEXTS = [
    "Sound is decent but nothing extraordinary. Bass is present but not as punchy as I hoped. Battery life is OK — about {hours} hours which is average. Fine for casual listening.",
    "These are acceptable for the price. The ANC is basic — reduces some ambient noise but don't expect miracles. Comfort is OK but I wouldn't wear them for more than 2 hours straight.",
    "Mixed feelings. Sound quality is good for music but call quality is below average. Build quality feels solid enough but the touch controls are finicky. You get what you pay for.",
]

_REVIEWER_NAMES = [
    "Rahul_K", "Priya_S", "Amit_R", "Sneha_M", "Vikram_P",
    "Ananya_T", "Karan_D", "Neha_G", "Arjun_V", "Deepika_L",
    "Suresh_N", "Meera_J", "Rohit_B", "Kavita_W", "Manish_C",
    "Pooja_H", "Aditya_F", "Shreya_O", "Nikhil_U", "Divya_I",
    "Rajesh_Q", "Swati_X", "Gaurav_Y", "Ritu_Z", "Sanjay_A",
    "Ishita_E", "Vishal_AA", "Tanvi_BB", "Harsh_CC", "Simran_DD",
    "Ashok_EE", "Pallavi_FF", "Kunal_GG", "Bhavna_HH", "Tushar_II",
    "Sakshi_JJ", "Mayank_KK", "Anjali_LL", "Pranav_MM", "Chetna_NN",
]

_SOURCES = ["amazon", "flipkart"]
_RATING_WEIGHTS = [5, 5, 5, 5, 5, 5, 5, 5,  # 40% → 5-star
                   4, 4, 4, 4, 4,              # 25% → 4-star
                   3, 3, 3, 3,                  # 20% → 3-star
                   2, 2,                         # 10% → 2-star
                   1]                            # 5%  → 1-star


def mock_scrape_reviews(product_id: str, count: int = 50) -> list[dict]:
    """
    Generate realistic fake reviews for testing.

    Args:
        product_id: Product identifier.
        count:      Number of fake reviews to generate.

    Returns:
        List of enriched review dicts ready for store_reviews().
    """
    reviews = []
    now = datetime.now()

    for i in range(count):
        rating = random.choice(_RATING_WEIGHTS)
        source = random.choice(_SOURCES)
        reviewer = random.choice(_REVIEWER_NAMES) + f"_{i}"
        date = (now - _td(days=random.randint(1, 90))).strftime("%Y-%m-%d")

        if rating >= 4:
            title = random.choice(_POSITIVE_TITLES)
            text = random.choice(_POSITIVE_TEXTS).format(
                days=random.randint(7, 90),
                hours=random.randint(5, 10),
            )
        elif rating <= 2:
            title = random.choice(_NEGATIVE_TITLES)
            text = random.choice(_NEGATIVE_TEXTS).format(
                mins=random.randint(5, 30),
                claimed=random.randint(8, 12),
                actual=random.randint(2, 4),
                hours=random.randint(2, 4),
            )
        else:
            title = random.choice(_NEUTRAL_TITLES)
            text = random.choice(_NEUTRAL_TEXTS).format(
                hours=random.randint(4, 6),
            )

        review_id = hashlib.md5(
            f"{reviewer}{date}{product_id}{i}".encode()
        ).hexdigest()

        reviews.append({
            "review_id": review_id,
            "product_id": product_id,
            "source": source,
            "rating": rating,
            "title": title,
            "text": text,
            "date": date,
            "reviewer_id": reviewer,
        })

    logger.info("Mock scraper: generated %d reviews for %s", count, product_id)
    return reviews


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Quick test — requires .env with SCRAPER_API_KEY and a product URL
    test_url = os.getenv("MASTER_BUDS_1_FLIPKART_URL")
    if not test_url or test_url.startswith("https://www.flipkart.com/product-url-here"):
        print("⚠️  Set MASTER_BUDS_1_FLIPKART_URL in .env to test live scraping.")
        print("Running syntax check only — module loaded successfully ✅")
    else:
        reviews = scrape_reviews(
            "master_buds_1", "flipkart", test_url, max_pages=2
        )
        print(f"\nScraped {len(reviews)} reviews")
        if reviews:
            print(json.dumps(reviews[:2], indent=2, ensure_ascii=False))
