"""CLI entry point for the observed service benchmark."""
import sys
from pathlib import Path
from ...format import canonical_json, parse_json
from ...errors import ProvenanceError
from ..repo_repair.errors import InvestigationError
from .agent import OpenAIServiceAgent, RecordedServiceAgent
from .experiment import ServiceVerifier, run_experiment, render_report


def run_cli(args):
    try:
        if args.agent == 'recorded':
            with Path(args.responses).open('rb') as stream:
                data = stream.read(1048577)
            if len(data) > 1048576:
                raise InvestigationError('RESPONSES_LIMIT', 'options', 'Replay exceeds 1 MiB')
            steps = parse_json(data)
            if type(steps) is not list or not 1 <= len(steps) <= 12:
                raise InvestigationError('RESPONSES_FORMAT', 'options', 'Replay needs one to twelve tool steps')
            agent = RecordedServiceAgent(steps)
        else:
            agent = OpenAIServiceAgent(args.model)
        report = run_experiment(Path(args.case_dir), agent, ServiceVerifier(), args.scenario, args.max_steps)
    except (InvestigationError, ProvenanceError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    output = canonical_json(report)+b'\n' if args.json else render_report(report).encode()
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout.buffer.write(output)
    else:
        sys.stdout.write(output.decode())
    return {'ACCEPTED': 0, 'DETECTED': 0, 'HEALTHY': 0, 'UNRESOLVED': 4, 'ERROR': 1}.get(report['outcome'], 3)
