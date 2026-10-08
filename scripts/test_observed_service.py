"""Prompt locally for a key, then run healthy and regression API cases."""
import getpass
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def main():
    if sys.version_info < (3, 12):
        raise SystemExit('Python 3.12 or later is required')
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    if not environment.get('OPENAI_API_KEY'):
        environment['OPENAI_API_KEY'] = getpass.getpass('OpenAI API key (hidden): ').strip()
    if not environment['OPENAI_API_KEY']:
        raise SystemExit('An API key is required')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + str(os.getpid())
    outcomes = []
    for scenario in ('healthy', 'regression'):
        case = root/'work'/f'service-{scenario}-{stamp}'
        print(f'\nRunning {scenario}: {case}', flush=True)
        result = subprocess.run([sys.executable, '-m', 'provenance', 'observe-service',
                                 '--agent', 'openai', '--scenario', scenario, '--case-dir', str(case)],
                                cwd=root, env=environment)
        outcomes.append(result.returncode)
    return 0 if all(code == 0 for code in outcomes) else 1


if __name__ == '__main__':
    raise SystemExit(main())
