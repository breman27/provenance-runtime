"""Start the persistent watcher; prompt for an API key only in the local terminal."""
import argparse
import getpass
import os
import sys
from datetime import datetime
from pathlib import Path


def main():
    if sys.version_info < (3, 12):
        raise SystemExit('Python 3.12+ is required')
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description='Watch working-tree edits and continuously collect service observations')
    parser.add_argument('--repo', default='/Users/brett/workspace/provenance-observed-service')
    parser.add_argument('--agent', choices=('openai', 'none'), default='openai')
    parser.add_argument('--interval', type=int, default=5)
    parser.add_argument('--session-dir')
    parser.add_argument('--model')
    parser.add_argument('--approval', choices=('manual', 'auto'), default='manual')
    args = parser.parse_args()
    if args.agent == 'openai' and not os.environ.get('OPENAI_API_KEY'):
        key = getpass.getpass('OpenAI API key (hidden): ').strip()
        if not key:
            raise SystemExit('An API key is required')
        os.environ['OPENAI_API_KEY'] = key
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + str(os.getpid())
    session = args.session_dir or str(root/'work'/f'watch-{stamp}')
    sys.path.insert(0, str(root))
    from provenance.__main__ import main as run
    argv = ['watch-service', '--repo', args.repo, '--session-dir', session,
            '--agent', args.agent, '--interval', str(args.interval), '--approval', args.approval]
    if args.model:
        argv += ['--model', args.model]
    print(f'Watching: {args.repo}\nSession: {session}\nLeave this terminal open. Ctrl+C stops the watcher.', flush=True)
    return run(argv)


if __name__ == '__main__':
    raise SystemExit(main())
