---
name: voc-analyst
description: Voice of Customer analyst tools for scraping, storing, analyzing, and reporting on product reviews from Amazon and Flipkart.
metadata: {"openclaw":{"requires":{"env":["SCRAPER_API_KEY","GROQ_API_KEY","DB_PATH"]}}}
---

# VoC Analyst Skill

This skill gives you access to the full review intelligence pipeline for Master Buds 1 
and Master Buds Max. Use these tools in sequence to ingest, analyze, and report on 
customer feedback.

## Available Tools

### scrape_reviews(product_id, source, url, max_pages)
Scrapes public reviews from Amazon or Flipkart using ScraperAPI.
- product_id: "master_buds_1" or "master_buds_max"
- source: "amazon" or "flipkart"  
- url: Full product reviews URL
- max_pages: Number of review pages to scrape (default: 10)
- Returns: List of raw review dicts {rating, title, text, date, reviewer_id}
- Location: {baseDir}/tools/scrape.py

### store_reviews(reviews, product_id, source)
Stores scraped reviews in SQLite, skipping duplicates automatically.
- reviews: Output from scrape_reviews()
- product_id: "master_buds_1" or "master_buds_max"
- source: "amazon" or "flipkart"
- Returns: {new_count, skipped_count, total_in_db}
- Location: {baseDir}/tools/db.py

### analyze_reviews(product_id, batch_size)
Processes unanalyzed reviews (processed=0) through Groq LLM for sentiment and themes.
- product_id: Optional filter, or None for all unprocessed
- batch_size: Reviews per API call (default: 20)
- Returns: {processed_count, sentiment_breakdown, theme_breakdown}
- Location: {baseDir}/tools/analyze.py

### generate_global_report()
Queries entire database and generates global_actions.md segmented by team.
- No parameters needed
- Returns: Path to generated report file
- Location: {baseDir}/tools/report.py

### generate_delta_report(since_date)
Generates weekly_delta.md for reviews ingested after since_date.
- since_date: ISO date string (YYYY-MM-DD), default is 7 days ago
- Returns: Path to generated report file
- Location: {baseDir}/tools/report.py

### query_reviews(sql_query)
Executes a SELECT query against the reviews database for conversational Q&A.
- sql_query: Valid SQLite SELECT statement
- Returns: Query results as formatted table
- Location: {baseDir}/tools/db.py
