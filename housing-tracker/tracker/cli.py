"""Explicit local ingestion; opening the dashboard never scrapes a website."""
import argparse
import json
import os
from pathlib import Path

from tracker.archive import rebuild, index_archive, sync
from tracker.batch import collect_batch, replay_details
from tracker.band import prune_archive, prune_database
from tracker.probe import import_probe
from tracker.storage import backup, default_db, export_snapshot, import_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=default_db())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync")
    alerts = commands.add_parser('email-price-changes')
    alerts.add_argument('--archive', type=Path, required=True)
    alerts.add_argument('--to', required=True, nargs='+')
    alerts.add_argument('--dry-run', action='store_true')
    prune = commands.add_parser('prune-price-scope')
    prune.add_argument('--archive', type=Path, required=True)
    collection = commands.add_parser("collect")
    collection.add_argument("--archive", type=Path, required=True)
    collection.add_argument("--detail-limit", type=int, default=2)
    collection.add_argument("--request-limit", type=int, default=3)
    replay = commands.add_parser('replay-details')
    replay.add_argument('--archive', type=Path, required=True)
    replay.add_argument('--manifest', type=Path, required=True)
    replay.add_argument('--raw-dir', type=Path, required=True)
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
    if args.command == 'email-price-changes':
        from tracker.alerts import notify
        failed = False
        for recipient in dict.fromkeys(address.strip().lower() for address in args.to):
            try:
                result = notify(args.db, args.archive, recipient, dry_run=args.dry_run)
            except Exception as exc:
                # One failed recipient must not prevent delivery to the others.
                print(json.dumps(dict(status='email_failed', recipient=recipient, error=type(exc).__name__)))
                failed = True
                continue
            print(json.dumps(dict(result, recipient=recipient)))
            if os.environ.get('GITHUB_STEP_SUMMARY'):
                with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
                    summary.write(f"\nPrice email ({recipient}): **{result['status']}**; price changes: {result['changes']}.\n")
            if result['status'] == 'not_configured':
                print('::warning::Price email requires the HOUSING_SMTP_PASSWORD repository secret.')
        if failed:
            raise SystemExit(1)
    elif args.command == 'prune-price-scope':
        print(json.dumps(dict(archive_observations_removed=prune_archive(args.archive),
                              database_observations_removed=prune_database(args.db))))
        index_archive(args.archive)
    elif args.command == "collect":
        if not 0 <= args.detail_limit <= 100:
            parser.error("detail-limit must be between 0 and 100")
        if not 1 <= args.request_limit <= 6:
            parser.error('request-limit must be between 1 and 6')
        try:
            result = collect_batch(args.db, args.archive, args.request_limit, args.detail_limit)
            print(json.dumps(result))
            if os.environ.get('GITHUB_STEP_SUMMARY'):
                lines = [f"Batch: **{result['status']}**", "",
                         f"Source requests: {result.get('requests', 0)}; newly verified years: {result.get('years_added', 0)}.", ""]
                for school, progress in result.get('enrichment', {}).items():
                    lines.append(f"- {school}: {progress['known']}/{progress['total']} years verified; {progress['missing']} missing.")
                with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
                    summary.write('\n'.join(lines) + '\n')
        finally:
            index_archive(args.archive)
        if result['status'] in ('blocked', 'error'):
            raise SystemExit(1)
    elif args.command == 'replay-details':
        print(f'Reparsed {replay_details(args.db, args.archive, args.manifest, args.raw_dir)} saved details')
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
