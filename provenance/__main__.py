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
    observed = commands.add_parser('observe-service', help='investigate a sensor service through autonomous bounded tools')
    observed.add_argument('--agent', required=True, choices=('openai', 'recorded'))
    observed.add_argument('--case-dir', required=True, help='new private case directory')
    observed.add_argument('--scenario', choices=('regression', 'healthy'), default='regression')
    observed.add_argument('--model', help='API model; defaults to gpt-4.1-mini')
    observed.add_argument('--responses', help='recorded tool-step JSON array')
    observed.add_argument('--max-steps', type=int, choices=range(1, 13), default=8)
    observed.add_argument('--json', action='store_true')
    watch = commands.add_parser('watch-service', help='continuously observe a real service working tree')
    watch.add_argument('--repo', required=True)
    watch.add_argument('--session-dir', required=True, help='new directory for the continuous graph and logs')
    watch.add_argument('--agent', choices=('openai', 'none'), default='openai')
    watch.add_argument('--model')
    watch.add_argument('--interval', type=int, default=5)
    watch.add_argument('--max-steps', type=int, choices=range(1, 13), default=8)
    watch.add_argument('--max-ticks', type=int, help='optional bounded smoke run; normally runs until interrupted')
    args = parser.parse_args(argv)
    if args.command == 'watch-service':
        from pathlib import Path
        from .clients.observed_service.watch import ServiceWatcher
        from .clients.observed_service.agent import OpenAIServiceAgent
        from .clients.observed_service.experiment import ServiceVerifier
        from .clients.repo_repair.errors import InvestigationError
        try:
            if args.max_ticks is not None and args.max_ticks < 1:
                parser.error('--max-ticks must be positive')
            agent = OpenAIServiceAgent(args.model) if args.agent == 'openai' else None
            ServiceWatcher(Path(args.repo), Path(args.session_dir), ServiceVerifier(), agent,
                           args.interval, args.max_steps).run(args.max_ticks)
            return 0
        except (InvestigationError, ProvenanceError, OSError, UnicodeError) as error:
            print(str(error), file=sys.stderr)
            return 1
    if args.command == 'observe-service':
        if args.agent == 'recorded' and (not args.responses or args.model):
            parser.error('recorded mode requires --responses and does not accept --model')
        if args.agent != 'recorded' and args.responses:
            parser.error('live modes do not accept --responses')
        from .clients.observed_service.cli import run_cli
        return run_cli(args)
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
