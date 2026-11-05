"""Dry-run by default. Sending requires --send plus explicit environment opt-in."""

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from mochex_radar.alert_store import claim_notice, enqueue, finish_notice, initialize_alert_store, preview_pending
from mochex_radar.alerts import ResearchNotice
from mochex_radar.telegram import send_message

log = logging.getLogger(__name__)


async def dispatch_once(dsn: str, client: httpx.AsyncClient, token: str, chat_id: str, daily_limit: int):
    notice = await asyncio.to_thread(claim_notice, dsn, daily_limit)
    if notice is None:
        return "idle"
    result = await send_message(client, token, chat_id, notice.body)
    return await asyncio.to_thread(finish_notice, dsn, notice, result)


async def run_sender(dsn: str, token: str, chat_id: str, daily_limit: int, once: bool):
    async with httpx.AsyncClient() as client:
        while True:
            state = await dispatch_once(dsn, client, token, chat_id, daily_limit)
            log.info("alert worker outcome=%s", state)
            if once:
                return
            await asyncio.sleep(5)


def main():
    parser = argparse.ArgumentParser(description="Preview operational notices or run the Telegram outbox worker")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--send", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--enqueue-test", action="store_true")
    parser.add_argument("--notice-file", type=Path)
    args = parser.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        parser.error("DATABASE_URL required")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if args.send and (os.environ.get("TELEGRAM_SEND_ENABLED", "false").lower() != "true" or not token or not chat):
        parser.error("sending requires TELEGRAM_SEND_ENABLED=true and securely configured bot token and chat ID")
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        daily_limit = int(os.environ.get("TELEGRAM_DAILY_ATTEMPTS", "100"))
        if daily_limit < 1:
            raise ValueError("positive daily limit required")
        initialize_alert_store(dsn)
        if args.enqueue_test:
            now = datetime.now(timezone.utc)
            enqueue(dsn, ResearchNotice(asset_id="system:mochex-radar", kind="SYSTEM_TEST",
                rule_version="system-test-v1", known_at=now, expires_at=now + timedelta(hours=1),
                summary="Operational delivery test.", evidence=["Explicit operator test; no market signal."]))
        if args.notice_file:
            enqueue(dsn, ResearchNotice.model_validate_json(args.notice_file.read_text(encoding="utf-8")))
        if not args.send:
            # No claim, transport, attempt increment, or delivered transition occurs in preview mode.
            print(json.dumps({"mode": "dry_run", "notices": preview_pending(dsn)}, default=str))
            return
        asyncio.run(run_sender(dsn, token, chat, daily_limit, args.once))
    except Exception as exc:
        parser.exit(1, f"Alert worker stopped: {type(exc).__name__}; check configuration and services.\n")


if __name__ == "__main__":
    main()
