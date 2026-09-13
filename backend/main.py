"""Agent entrypoint: APScheduler wiring (PRD 1.2 - 100% automated pipeline).

Usage:
    .venv/bin/python -m backend.main --run-once   # one manual cycle, then exit
    .venv/bin/python -m backend.main              # long-running scheduler
"""
import argparse
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from backend import agent, config
from backend.db import init_db
from backend.modules.alerter import check_token_expiry, send_alert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agent.main")


def scheduled_cycle() -> None:
    """One scheduled pass of the full pipeline with alerting on failure."""
    try:
        summary = agent.run_all_once()
        logger.info("Cycle summary: %s", summary)
    except Exception as exc:  # noqa: BLE001 - scheduler must never die
        logger.exception("Scheduled cycle crashed")
        send_alert(f"Scheduler cycle crashed: {str(exc)[:200]}")


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(scheduled_cycle, "interval", minutes=config.SCAN_INTERVAL_MINUTES,
                      id="pipeline_cycle", max_instances=1, coalesce=True)
    # Publishing ticks more often so drip-feed entries fire close to schedule.
    scheduler.add_job(agent.publish_due_entries, "interval", minutes=15,
                      id="publish_tick", max_instances=1, coalesce=True)
    # Token expiry watch (PRD 6: alert 5 days before expiry) - daily.
    scheduler.add_job(check_token_expiry, "interval", hours=24,
                      id="token_expiry_watch", max_instances=1, coalesce=True)
    return scheduler


def main() -> None:
    parser = argparse.ArgumentParser(description="Automated Video Syndication Agent")
    parser.add_argument("--run-once", action="store_true", help="run one cycle and exit")
    args = parser.parse_args()

    init_db()
    check_token_expiry()

    if args.run_once:
        logger.info("Running single cycle (DRY_RUN=%s)...", config.DRY_RUN)
        summary = agent.run_all_once()
        logger.info("Summary: %s", summary)
        return

    logger.info("Starting scheduler (DRY_RUN=%s, scan every %d min)...",
                config.DRY_RUN, config.SCAN_INTERVAL_MINUTES)
    scheduled_cycle()  # immediate first pass
    build_scheduler().start()


if __name__ == "__main__":
    main()
