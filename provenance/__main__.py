"""Run the local provenance demonstration."""
import argparse
import sqlite3
import sys

from .demo import run_demo
from .errors import ProvenanceError
from .format import canonical_json
from .store import Store


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Immutable evidence and a simulated verified effect")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="prove the gate and stale-justification behavior")
    demo.add_argument("--db", required=True, help="fresh SQLite path, or :memory:")
    args = parser.parse_args(argv)
    try:
        with Store(args.db) as store:
            report = run_demo(store)
        sys.stdout.buffer.write(canonical_json(report) + b"\n")
        return 0
    except (ProvenanceError, sqlite3.Error, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
