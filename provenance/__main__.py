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
    investigation = commands.add_parser('investigate', help='run a bounded agent investigation of the bundled clamp fixture')
    investigation.add_argument('--agent', required=True, choices=('openai', 'codex', 'recorded'))
    investigation.add_argument('--case-dir', required=True, help='new private case directory; existing paths are preserved')
    investigation.add_argument('--scenario', choices=('normal', 'stale-source'), default='normal')
    investigation.add_argument('--hint', help='human report supplied after the first reasoning round')
    investigation.add_argument('--model', help='optional API or Codex model; OpenAI defaults to gpt-4.1-mini')
    investigation.add_argument('--responses', help='recorded mode: JSON array of one to three response objects')
    investigation.add_argument('--max-rounds', type=int, choices=(1, 2, 3), default=3)
    investigation.add_argument('--json', action='store_true', help='machine-readable output; default is readable Markdown')
    args = parser.parse_args(argv)
    if args.command == 'investigate':
        if args.agent == 'recorded' and (not args.responses or args.model):
            parser.error('recorded mode requires --responses and does not accept --model')
        if args.agent != 'recorded' and args.responses:
            parser.error('live modes do not accept --responses')
        from .clients.repo_repair.report import run_cli
        return run_cli(args)
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
