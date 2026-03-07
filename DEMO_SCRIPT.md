# 🎥 VoC Agent — 5-Minute Loom Demo Script

This script provides a step-by-step walkthrough for recording a 5-minute video demonstration of the Autonomous VoC Intelligence Agent.

## Setup & Pre-requisites (0:00 - 0:30)
- **Visual:** Terminal window open to the `voc-agent` project directory. VS Code (or your IDE) open alongside it.
- **Action:** Briefly show the `.env` file containing the `GROQ_API_KEY` and the product URLs. 
- **Talking Point:** "This is the Autonomous VoC Agent. It uses ScraperAPI to fetch live reviews from Amazon and Flipkart, and an LLM to analyze sentiment and extract product themes. I've populated the environment file with the necessary API keys and target URLs."

---

## Step 1: Database Initialization & Agent Overview (0:30 - 1:00)
- **Command:** `python agent.py --stats`
- **Visual:** Terminal showing the database stats (Total Reviews, Breakdown by Product/Sentiment).
- **Talking Point:** "The agent operates autonomously via taking actions through tools. It stores all scraped knowledge in a central SQLite database. Here, we can see the current statistics of our review dataset."

---

## Step 2: The Actionable Markdown Reports (1:00 - 2:00)
- **Command:** Open `reports/global_actions.md` and `reports/weekly_delta.md` in your editor.
- **Visual:** Split screen showing the Markdown files. Scroll through the Global report.
- **Talking Point:** "The agent autonomously generates these reports. Let's look at the Global Action Intelligence Report. Notice how it categorizes feedback by Product Team themes, like 'Build Quality' or 'Comfort & Fit', and provides raw review metadata as evidence. The Weekly Delta report acts as an early warning system, automatically highlighting spikes or drops—like a 32% drop in Comfort & Fit mentions—alerting the team to new trends."

---

## Step 3: The Delta Duplication Proof (2:00 - 3:00)
- **Command:** Open `logs/delta_log.json` in your editor.
- **Visual:** Show the JSON structure highlighting `total_new` vs `mock_delta` numbers.
- **Talking Point:** "Data integrity is critical. The agent guarantees NO duplicate reviews are ingested by utilizing physical database constraints. Here is the output log from a simulated second run. We intentionally injected 10 duplicate reviews alongside 25 new ones. As proven in the JSON output, exactly 25 new reviews were captured, and the 10 duplicates were correctly caught and skipped by the SQLite `UNIQUE` hash constraint."

---

## Step 4: Conversational Querying (Text-to-SQL) (3:00 - 4:30)
- **Command:** Run the conversational command live: 
  `python agent.py --query "What is the most common complaint about Master Buds Max?"`
- **Visual:** Terminal executing the command, showing the generated SQL, the raw data table, and Molly's final summary. 
- **Talking Point:** "Finally, because the agent acts as a grounded intelligence engine, we can ask it novel questions using natural language. Watch as it translates this question into a valid SQLite query, fetches the raw data without hallucinating, and summarizes the top complaints accurately based strictly on the stored database context."

---

## Conclusion (4:30 - 5:00)
- **Visual:** The architecture diagram in `README.md`.
- **Talking Point:** "This completes the end-to-end pipeline. The entire process is fully automated via GitHub Actions, meaning this runs without manual intervention every single week, continuously updating the company's product teams with crucial customer intelligence. Thank you."
