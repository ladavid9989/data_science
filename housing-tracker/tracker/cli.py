"""Explicit local ingestion; opening the dashboard never scrapes a website."""
import argparse
import json
from pathlib import Path

from tracker.archive import rebuild, index_archive, sync
from tracker.collect import collect
from tracker.probe import import_probe
from tracker.storage import backup, default_db, export_snapshot, import_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=default_db())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync")
    collection = commands.add_parser("collect")
    collection.add_argument("--archive", type=Path, required=True)
    collection.add_argument("--detail-limit", type=int, default=25)
    restore = commands.add_parser("rebuild")
    restore.add_argument("archive", type=Path)
    index = commands.add_parser("index")
    index.add_argument("archive", type=Path)
    probe = commands.add_parser("import-probe")
    probe.add_argument("directory", type=Path)
    imp = commands.add_parser("import-json")
    imp.add_argument("files", nargs="+", type=Path)
    exp = commands.add_parser("export-run")
    exp.add_argument("run_id")
    exp.add_argument("destination", type=Path)
    back = commands.add_parser("backup")
    back.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.command == "collect":
        if not 0 <= args.detail_limit <= 100:
            parser.error("detail-limit must be between 0 and 100")
        results = collect(args.db, args.archive, args.detail_limit)
        index_archive(args.archive)
        if len(results) != 2 or any(r["quality"] not in {"complete", "source_complete"} for r in results):
            raise SystemExit(1)
    elif args.command == "sync":
        print(f"Imported {sync(args.db)} cloud snapshots")
    elif args.command == "rebuild":
        print(f"Restored {rebuild(args.db, args.archive)} snapshots")
    elif args.command == "index":
        print(f"Indexed {len(index_archive(args.archive))} snapshots")
    elif args.command == "import-probe":
        print(import_probe(args.db, args.directory))
    elif args.command == "import-json":
        for file in args.files:
            print(file.name, import_snapshot(args.db, json.loads(file.read_text(encoding="utf-8-sig"))))
    elif args.command == "export-run":
        with args.destination.open("x", encoding="utf-8") as file:
            json.dump(export_snapshot(args.db, args.run_id), file, ensure_ascii=False, indent=2)
        print(args.destination)
    elif args.command == "backup":
        print(f"Backup SHA256: {backup(args.db, args.destination)}")


if __name__ == "__main__":
    main()
