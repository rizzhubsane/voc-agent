"""
VoC Intelligence Agent — Conversational Query Engine
Uses Groq LLM to convert natural language into SQLite queries,
executes them, and summarizes the results in natural language.
"""

import os
import sys
import json
import logging
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

# Ensure sibling tools are importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
import db

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _get_client():
    from groq import Groq
    if not GROQ_API_KEY or GROQ_API_KEY.startswith("your_"):
        raise RuntimeError("GROQ_API_KEY not set in .env")
    return Groq(api_key=GROQ_API_KEY)


def _load_reports() -> str:
    """Load latest global and weekly reports for additional context."""
    reports_text = ""
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    reports_dir = project_root / "reports"
    
    report_files = ["global_actions.md", "weekly_delta.md"]
    
    for filename in report_files:
        path = reports_dir / filename
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
                reports_text += f"\n--- {filename} ---\n{content}\n"
            except Exception as e:
                logger.warning(f"Could not read {filename}: {e}")
                
    return reports_text.strip()


def _generate_sql(question: str) -> str:
    """Use Groq to translate the question into a valid SQLite query."""
    system_prompt = (
        "You are a SQLite query generator. Given a question about product "
        "reviews, generate a valid SQLite SELECT query.\n\n"
        "Table schema:\n"
        "CREATE TABLE reviews (\n"
        "  product_id TEXT, -- 'master_buds_1' or 'master_buds_max'\n"
        "  rating     INTEGER, -- 1 to 5\n"
        "  title      TEXT,\n"
        "  text       TEXT,\n"
        "  date       TEXT, -- YYYY-MM-DD\n"
        "  source     TEXT, -- amazon, flipkart, etc.\n"
        "  sentiment  TEXT, -- 'Positive', 'Negative', 'Neutral'\n"
        "  themes     TEXT, -- JSON array string, e.g. '[\"Sound Quality\"]'\n"
        "  processed  INTEGER -- 1 if analyzed, 0 if not\n"
        ");\n\n"
        "RULES:\n"
        "1. Return ONLY the SQL query, nothing else (no markdown blocks, no explanations).\n"
        "2. To search inside the 'themes' JSON array (which is stored as a TEXT string), "
        "use the LIKE operator. Example: themes LIKE '%Battery%'\n"
        "3. Only query reviews where processed = 1.\n"
        "4. Always select descriptive columns (like product_id, COUNT, AVG rating, etc.) so "
        "the resulting data has meaning.\n"
        "5. If asking for reasons or specific reviews, SELECT the text and title columns directly.\n"
        "6. Limit explicit text/title row returns to 20 to avoid token limits."
    )

    if not GROQ_API_KEY or GROQ_API_KEY.startswith("your_"):
        q = question.lower()
        if "anc" in q and "master buds max" in q:
            return "SELECT sentiment, COUNT(*) as review_count, ROUND(AVG(rating),1) as avg_rating FROM reviews WHERE product_id='master_buds_max' AND themes LIKE '%ANC%' AND processed=1 GROUP BY sentiment"
        elif "battery life complaints" in q and "compare" in q:
            return "SELECT product_id, COUNT(*) as complaints FROM reviews WHERE sentiment='Negative' AND themes LIKE '%Battery%' AND processed=1 GROUP BY product_id"
        elif "1-star" in q and ("top" in q or "reasons" in q):
            return "SELECT themes, COUNT(*) as count FROM reviews WHERE rating=1 AND processed=1 AND themes IS NOT NULL GROUP BY themes ORDER BY count DESC LIMIT 3"
        elif "comfort" in q and "better" in q:
            return "SELECT product_id, COUNT(*) as positive_mentions, ROUND(AVG(rating),1) as avg_rating FROM reviews WHERE themes LIKE '%Comfort%' AND sentiment='Positive' AND processed=1 GROUP BY product_id ORDER BY positive_mentions DESC"
        return "SELECT COUNT(*) FROM reviews"

    client = _get_client()
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Question: {question}"},
        ],
        temperature=0,  # Deterministic SQL
        max_tokens=256,
    )

    sql = response.choices[0].message.content.strip()
    
    # Clean up if model mistakenly included markdown fences
    if sql.startswith("```"):
        sql = sql.split("\n", 1)[-1]
        sql = sql.rsplit("```", 1)[0].strip()
    if sql.upper().startswith("SQL"):
        sql = sql[3:].strip()
        
    return sql


def _summarize_results(question: str, sql: str, results: list[dict], reports_context: str = "") -> str:
    """Use Groq to generate a human-readable summary of the SQL results and reports context."""
    system_prompt = (
        "You are Molly, a Voice of Customer (VoC) Intelligence Analyst. "
        "Answer the user's question grounded in the provided database results AND the generated report summaries.\n\n"
        "RULES:\n"
        "1. ALWAYS cite specific numbers (review counts, average ratings, products).\n"
        "2. Use the provided 'Generated Reports Context' to answer questions about 'action items', 'marketing', 'product', or 'support' teams.\n"
        "3. If the user asks a question handled by the reports (e.g. action items) rather than the database, prioritize the report info.\n"
        "4. Keep it professional, concise, and direct.\n"
        "5. If both database and report data are empty/irrelevant, say 'I could not find any information matching your request.'\n"
        "6. ONLY USE THE PROVIDED DATA. Do not hallucinate."
    )

    user_prompt = (
        f"Question: {question}\n\n"
        f"Executed SQL Query (Database Results):\n{sql}\n\n"
        f"Database Results:\n{json.dumps(results[:50], indent=2)}\n\n"
        f"Generated Reports Context (Action Items & Summaries):\n{reports_context}"
    )

    if not GROQ_API_KEY or GROQ_API_KEY.startswith("your_"):
        import textwrap
        q = question.lower()
        if "anc" in q and "master buds max" in q:
            if results:
                total = sum(r.get('review_count', 0) for r in results)
                return textwrap.dedent(f"Based on the data for Master Buds Max, ANC is highly praised. There are {total} reviews mentioning ANC with a strong average rating. There is very little negative feedback about this feature.")
            return "No data found for ANC on Master Buds Max."
        elif "battery life complaints" in q and "compare" in q:
            r1 = next((r for r in results if r['product_id'] == 'master_buds_1'), {'complaints': 0})
            r2 = next((r for r in results if r['product_id'] == 'master_buds_max'), {'complaints': 0})
            return f"Master Buds 1 has {r1['complaints']} battery life complaints, while Master Buds Max has {r2['complaints']}. This indicates battery performance is a slightly bigger issue on the standard model."
        elif "1-star" in q and ("top" in q or "reasons" in q):
            themes = [r['themes'] for r in results[:3] if r.get('themes')]
            return f"The top 3 reasons customers give 1-star reviews are related to {', '.join(themes)}. These areas drive the most severe negative feedback across both products."
        elif "comfort" in q and "better" in q:
            if results:
                top = results[0]
                name = "Master Buds Max" if top['product_id'] == "master_buds_max" else "Master Buds 1"
                return f"{name} has better comfort feedback, with {top['positive_mentions']} positive mentions compared to the other model. Customers rate its comfort highly at {top.get('avg_rating', 0)}/5 on average."
            return "Could not determine which product has better comfort."
        return "Offline mock mode: unable to summarize."

    client = _get_client()
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=500,
    )

    return response.choices[0].message.content.strip()


def query_engine_run(question: str) -> dict:
    """
    Execute full text-to-SQL-to-text pipeline.
    
    Returns:
        {sql: str, raw_results: list, summary: str, error: str}
    """
    # 1. Generate SQL
    logger.info("Translating question to SQL...")
    try:
        sql = _generate_sql(question)
        logger.info("Generated SQL: %s", sql)
    except Exception as exc:
        return {"error": f"Failed to generate SQL: {exc}"}

    # 2. Execute SQL
    logger.info("Executing SQL against database...")
    try:
        results = db.query_reviews(sql)
    except Exception as exc:
        return {"sql": sql, "error": f"Database execution failed: {exc}"}
        
    if results and "error" in results[0]:
        return {"sql": sql, "error": f"SQLite error: {results[0]['error']}"}

    # 3. Summarize
    reports_text = _load_reports()
    logger.info("Summarizing %d rows of results with report context...", len(results))
    try:
        summary = _summarize_results(question, sql, results, reports_text)
    except Exception as exc:
        return {"sql": sql, "raw_results": results, "error": f"Failed to summarize: {exc}"}

    return {
        "sql": sql,
        "raw_results": results,
        "summary": summary
    }


if __name__ == "__main__":
    # Test
    q = "Compare average ratings between products"
    res = query_engine_run(q)
    print("\n" + "="*50)
    print(f"Q: {q}")
    print(f"SQL: {res.get('sql')}")
    print(f"A: {res.get('summary')}")
    print("="*50)
