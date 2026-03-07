#!/usr/bin/env python3
"""
local_scheduler.py — Local background daemon for weekly VoC pipeline.

Usage:
    python local_scheduler.py &          # Run as background daemon
    python local_scheduler.py --once     # Run pipeline once and exit
    python local_scheduler.py --test     # Dry-run: print next scheduled time

The scheduler runs the full pipeline (ingest → analyze → report)
every Sunday at midnight IST (00:00 Asia/Kolkata).
"""

import argparse
import subprocess
import sys
import time
import logging
from datetime import datetime

import schedule

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PIPELINE_CMD = [sys.executable, "agent.py", "--pipeline"]
SCHEDULE_TIME = "00:00"  # midnight IST
SCHEDULE_DAY = "sunday"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SCHEDULER] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/scheduler.log", mode="a"),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------
def run_pipeline():
    """Execute the full VoC pipeline via subprocess."""
    logger.info("=" * 60)
    logger.info("🦞 Scheduled pipeline triggered at %s", datetime.now().isoformat())
    logger.info("=" * 60)

    try:
        result = subprocess.run(
            PIPELINE_CMD,
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour max
        )
        logger.info("Pipeline stdout:\n%s", result.stdout[-2000:] if result.stdout else "(empty)")
        if result.returncode != 0:
            logger.error("Pipeline failed (exit %d):\n%s", result.returncode, result.stderr[-1000:])
        else:
            logger.info("✅ Pipeline completed successfully")
    except subprocess.TimeoutExpired:
        logger.error("❌ Pipeline timed out after 1 hour")
    except Exception as exc:
        logger.error("❌ Pipeline error: %s", exc)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
def start_scheduler():
    """Start the weekly schedule loop."""
    # Schedule for every Sunday at midnight
    schedule.every().sunday.at(SCHEDULE_TIME).do(run_pipeline)

    next_run = schedule.next_run()
    logger.info("🗓️  VoC Scheduler started")
    logger.info("   Schedule: Every %s at %s", SCHEDULE_DAY, SCHEDULE_TIME)
    logger.info("   Next run: %s", next_run)
    logger.info("   PID: %d", __import__("os").getpid())
    logger.info("   Stop with: kill %d", __import__("os").getpid())

    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="VoC Intelligence Agent — Local Scheduler Daemon",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run the pipeline once immediately and exit",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Dry run: show next scheduled time and exit",
    )
    args = parser.parse_args()

    if args.once:
        logger.info("Running pipeline once (--once mode)")
        run_pipeline()
    elif args.test:
        schedule.every().sunday.at(SCHEDULE_TIME).do(lambda: None)
        print(f"📅 Schedule: Every {SCHEDULE_DAY} at {SCHEDULE_TIME}")
        print(f"📅 Next run: {schedule.next_run()}")
        print(f"📅 Current time: {datetime.now()}")
    else:
        start_scheduler()


if __name__ == "__main__":
    main()
