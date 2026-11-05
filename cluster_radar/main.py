"""Starter CLI only: no live provider access or financial transactions."""

import argparse
import json
import os
from importlib.metadata import PackageNotFoundError, version


def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster Radar — research-only starter CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check local configuration without calling providers")
    sub.add_parser("demo", help="Print sample watch notifications (not real market data)")
    args = parser.parse_args()

    if args.command == "doctor":
        try:
            app_version = version("cluster-radar")
        except PackageNotFoundError:
            app_version = "development"
        print(f"Cluster Radar {app_version} — research-only scaffold")
        print("Live scanner: NOT YET IMPLEMENTED")
        for key in ("BIRDEYE_API_KEY", "HELIUS_API_KEY", "RUGCHECK_API_KEY", "TELEGRAM_BOT_TOKEN"):
            print(f"{key}: {'configured' if os.getenv(key) else 'not configured'}")
        print("No network calls or trades were performed.")
    elif args.command == "demo":
        print(json.dumps({
            "example_only": True,
            "token": "DEMO-MEME",
            "type": "PUMP_WATCH",
            "pump_score": 82,
            "risk": "UNKNOWN",
            "approved_alert": False,
            "message": "Illustrative evidence only. No real on-chain verification; no trade advice.",
        }, indent=2))


if __name__ == "__main__":
    main()
