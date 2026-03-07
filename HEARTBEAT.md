---
schedule: "0 0 * * 0"
timezone: "Asia/Kolkata"
---

# Weekly VoC Intelligence Heartbeat

Every Sunday at midnight IST, run the full autonomous pipeline:

## Trigger Conditions
- Run if today is Sunday AND last ingestion was more than 6 days ago
- Also run if manually triggered via: `openclaw run heartbeat`

## Autonomous Actions

1. **Check last run date**
   Query: SELECT MAX(run_date) FROM ingestion_log
   If result is NULL or > 6 days ago, proceed. Otherwise, skip.

2. **Scrape new reviews** for both products from both sources
   Use scrape_reviews() with the URLs from .env
   Focus on reviews newer than the last ingestion date

3. **Store new reviews**
   Use store_reviews() — deduplication is automatic via UNIQUE constraint on review_id
   Save count of new reviews to delta_log.json for proof

4. **Analyze new reviews**
   Run analyze_reviews() on all rows where processed=0

5. **Generate reports**
   Run generate_global_report() → saves to reports/global_actions.md
   Run generate_delta_report() → saves to reports/weekly_delta.md

6. **Log completion**
   INSERT into ingestion_log with run_date, counts per product

## Completion Message
After pipeline completes, send summary:
"✅ Weekly VoC run complete. Scraped [N] new reviews. 
Master Buds 1: [X] new | Master Buds Max: [Y] new.
Top new theme: [THEME]. Report saved to reports/"
