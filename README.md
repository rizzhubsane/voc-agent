# Autonomous VoC Intelligence Agent 🦞

> An OpenClaw-powered AI agent that autonomously scrapes, analyzes, and reports on 
> customer reviews for audio wearables — with zero manual execution after setup.

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)
![Node.js 22+](https://img.shields.io/badge/Node.js-22%2B-green)

The **VoC Intelligence Agent ("Molly")** is an autonomous AI worker designed to continuously monitor public product feedback. Built on the open-source OpenClaw framework, Molly operates safely using a structured ReAct loop: identifying what raw data she needs, calling local tool functions to fetch and analyze it, and saving structured product intelligence to an SQLite database. 

This is not a simple linear script; it is a continuously observing pipeline that requires zero human intervention to generate weekly delta reports for product, marketing, and support teams.

---

## 🏗️ Architecture

```ascii
                                ┌─────────────────────────┐
                                │                         │
                                │   OpenClaw Framework    │
   ┌──────────────────┐         │  (Autonomous Engine)    │         ┌────────────────────┐
   │                  │◄────────┼─ 1. Reads SOUL.md       │         │                    │
   │  LLM (Groq)      │         │  2. Triggers Pipeline   │────────►│  ScraperAPI        │
   │  llama-3.3-70b   ├────────►│  3. Formulates Queries  │         │  (Amazon & Flipkart)│
   │                  │         │  4. ReAct Loop Control  │         │                    │
   └──────────▲───────┘         │                         │         └──────────┬─────────┘
              │                 └───────────┬─────────────┘                    │
              │                             │                                  │
              │                             ▼                                  │
              │                 ┌─────────────────────────┐                    │
              │                 │   skills/voc-analyst/   │                    │
              └─────────────────┤      Python Tools       │◄───────────────────┘
               Classification   │  - scrape.py            │  HTML Parsing
               & Summarization  │  - db.py (SQLite)       │  & Deduplication
                                │  - analyze.py           │
                                │  - report.py            │
                                │  - query_engine.py      │
                                └───────────┬─────────────┘
                                            │
                                            ▼
                                ┌─────────────────────────┐
                                │    Local Data Store     │
                                │        db.sqlite        │
                                └───────────┬─────────────┘
                                            │
                          ┌─────────────────┴─────────────────┐
                          ▼                                   ▼
              ┌───────────────────────┐            ┌──────────────────────┐
              │  global_actions.md    │            │  weekly_delta.md     │
              │  (Historical context) │            │  (Spikes & alerts)   │
              └───────────────────────┘            └──────────────────────┘
```

### Why this is an AGENT, not just automation:
Automation implies a fixed, deterministic sequence of steps. While parsing HTML is deterministic, identifying the *themes* and *sentiment* of human language is not. Furthermore, the agent is capable of conversational querying—when you ask *"What do customers say about ANC?"*, OpenClaw dynamically formulates a SQL query, executes it, reads the unknown database result, and formulates a grounded natural language response. This relies on the **ReAct (Reasoning + Acting)** paradigm to perceive, plan, act, and reflect.

---

## 🗂️ Repository Structure

```
voc-agent/
├── agent.py               # Main CLI orchestrator (ingest, analyze, report, query)
├── local_scheduler.py     # Local daemon for weekly cron execution
├── db.sqlite              # Single-file SQLite database (generated)
├── requirements.txt       # Python dependencies
├── .env.example           # Template for required API keys and product URLs
├── .github/
│   └── workflows/
│       └── weekly-ingest.yml # Fully automated autonomous pipeline runner
├── logs/
│   └── delta_log.json     # JSON proof that duplicates are successfully caught
├── reports/
│   ├── global_actions.md  # All-time segmented markdown action plan
│   └── weekly_delta.md    # 7-day trend analysis and urgency alerts
└── skills/
    └── voc-analyst/
        ├── SKILL.md       # OpenClaw tool registration definitions
        ├── HEARTBEAT.md   # OpenClaw autonomous trigger schedule definition
        └── tools/
            ├── scrape.py       # Amazon/Flipkart scraping & dedupe logic
            ├── db.py           # SQLite abstraction layer
            ├── analyze.py      # LLM sentiment and JSON theme classification
            ├── report.py       # Markdown report compilation engine
            └── query_engine.py # Text-to-SQL conversational query handler
```

---

## ⚙️ Prerequisites
- **Node.js 22+** (required to run the OpenClaw autonomous core)
- **Python 3.10+** (handles all skill logic)
- **ScraperAPI Key** (Free tier — bypasses retail CAPTCHAs)
- **Groq API Key** (Free tier — runs the `llama-3.3-70b-versatile` intelligence engine)

---

## 🚀 Setup (Step-by-Step)

1. **Install OpenClaw:**
   ```bash
   npm i -g openclaw
   ```
2. **Clone this repository:**
   ```bash
   git clone https://github.com/yourusername/voc-agent.git
   cd voc-agent
   ```
3. **Install Python Tools:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Configure Environment:**
   Copy the example environment file and insert your API keys.
   ```bash
   cp .env.example .env
   ```
5. **Initialize Database:**
   ```bash
   python agent.py --stats
   ```
6. **Onboard OpenClaw Engine:**
   When prompted, select `Groq` as the LLM provider.
   ```bash
   openclaw onboard
   ```
7. **Register Agent Skill:**
   This allows OpenClaw to call the Python modular tools.
   ```bash
   openclaw skill install ./skills/voc-analyst
   ```
8. **Test the Agent:**
   ```bash
   openclaw message "What skills do you have?"
   ```

---

## 📋 Usage

### Manual Pipeline Run
Runs the entire process sequentially: scrape new data → analyze with LLM → generate reports.
```bash
python agent.py --pipeline
```

### Individual Execution Steps
```bash
python agent.py --ingest      # Scrape new reviews from retail URLs
python agent.py --analyze     # Run sentiment/theme classification on new data
python agent.py --report      # Generate the output markdown files
python agent.py --stats       # Show high-level database summary
```

### Conversational Querying (Groq Text-to-SQL)
Ask the agent natural language questions about the collected data.
```bash
python agent.py --query "Compare ANC feedback between both products"
python agent.py --query "What are the top reasons for 1-star reviews?"
```

### Autonomous Mode (via OpenClaw)
Start the background engine to let OpenClaw work autonomously.
```bash
openclaw start
```
Then, you can talk to Molly:
```bash
openclaw message "Run the weekly VoC pipeline"
openclaw message "What are the top complaints about Master Buds Max?"
```

---

## 🗄️ Database Schema

The SQLite database (`db.sqlite`) serves as the central brain. Duplication is prevented physically via a `UNIQUE` constraint on `review_id` (an MD5 hash of reviewer ID, product, and date).

```sql
CREATE TABLE reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  TEXT    NOT NULL,
    review_id   TEXT    UNIQUE NOT NULL,
    rating      INTEGER,
    title       TEXT,
    text        TEXT,
    date        TEXT,
    source      TEXT,
    sentiment   TEXT    DEFAULT NULL,
    themes      TEXT    DEFAULT NULL,  -- Stored as JSON string
    processed   INTEGER DEFAULT 0,
    ingested_at TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE ingestion_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date       TEXT,
    product_id     TEXT,
    new_reviews    INTEGER,
    total_reviews  INTEGER
);
```

---

## 📊 Report Outputs

The agent generates two primary files into the `reports/` folder:

### 1. `global_actions.md`
A comprehensive, all-time analysis of the database. It segments actionable items to granular corporate teams (Product, Marketing, Support).
**Example Output:**
> **Build Quality:** 13 negative mentions (15% of 86 total) — Average rating when mentioned: 3.95/5
> *Supporting evidence:* "Call quality is terrible. People on the other end say I sound muffled and distant..."

### 2. `weekly_delta.md`
Focuses purely on the last 7 days of ingested reviews to identify sudden spikes or drops in specific sentiments.
**Example Output:**
> **🚨 Spikes & Alerts (>20% change)**
> **Comfort & Fit — DOWN 32%**
> - Previous week: 38 mentions | This week: 26 mentions
> - *Recommended Action:* Monitor — trend improving

---

## ⏰ Scheduling

### GitHub Actions (Highly Recommended)
An automated runner is included in `.github/workflows/weekly-ingest.yml`. It spins up every Sunday at midnight IST, runs the full ingestion pipeline, generates the reports, and auto-commits the compiled `db.sqlite` back to the repository.
**Required GitHub Secrets:**
- `SCRAPER_API_KEY`
- `GROQ_API_KEY`
- All product URL keys (e.g. `MASTER_BUDS_1_AMAZON_URL`)

### Local Scheduling (Daemon)
To run the automated loop on a local server/Raspberry Pi:
```bash
python local_scheduler.py &
```

---

## 🔒 Data Privacy
All ingested data is sourced strictly from publicly available anonymized product review pages on Amazon India and Flipkart. No proprietary corporate, internal IP, or private user-generated data outside of public reviews is collected, processed, or transmitted to LLMOps APIs.

---

## 🎯 Assignment Criteria Met

| Criterion | Implementation |
|-----------|---------------|
| **Agent Autonomy** | OpenClaw ReAct loop & GitHub Actions execute without manual intervention. |
| **Delta Handling** | `UNIQUE` SQLite constraint + ID hashing physically prevents duplicate scraping. |
| **Actionability** | Reports divide tasks by Product/Marketing/Support utilizing strict JSON taxonomies. |
| **Grounding** | All `agent.py --query` assertions literally query SQL and cite raw numbers; zero hallucination. |

---

## 📁 Deliverables Checklist

- [x] Code Repository (this repo)
- [x] `README.md` (this file)
- [x] `SOUL.md` (agent identity configuration)
- [x] `db.sqlite` (initial populated database)
- [x] `logs/delta_log.json` (Proof verifying delta duplication catches)
- [x] `reports/global_actions.md` (Historical action item list)
- [x] `reports/weekly_delta.md` (Trailing 7-day spike alerts)

---
*Created by Rishabh | Built for the Advanced Agentic Pipeline Architecture Assignment.*
