from __future__ import annotations

import argparse

from src.pipeline import Pipeline
from src.utils import configure_logging


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Local-first AI job matching assistant")
    parser.add_argument(
        "command",
        choices=["run-all", "collect", "score", "report", "email-report"],
        help="Pipeline command to run",
    )
    args = parser.parse_args()
    pipeline = Pipeline()

    if args.command == "run-all":
        pipeline.run_all()
    elif args.command == "collect":
        pipeline.collect()
    elif args.command == "score":
        pipeline.score()
    elif args.command == "report":
        pipeline.report()
    elif args.command == "email-report":
        pipeline.email_report()


if __name__ == "__main__":
    main()
