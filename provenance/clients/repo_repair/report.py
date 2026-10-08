"""Readable investigation reports and CLI boundary."""
import sys
from pathlib import Path
from ...errors import ProvenanceError
from ...format import canonical_json, parse_json
from .agent import CodexAgent, RecordedAgent
from .coordinator import InvestigationOptions, InvestigationReport, run_investigation
from .errors import InvestigationError
from .verifier import DockerVerifier
from .case import safe_path
from .openai_agent import OpenAIAgent
from ..reporting import render_investigation_report



def render_report(report):
    provider = {'codex': 'Codex', 'openai': 'OpenAI API'}.get(report.backend, report.backend)
    mode = f'Live {provider} reasoning' if report.live_agent else 'Recorded reasoning (replay; no live model call)'
    if report.live_agent and not report.rounds and report.error and report.error['stage'] in ('preflight', 'options', 'baseline'):
        mode = f'{provider} mode (no completed model response)'
    return render_investigation_report(report.as_dict(), title='Investigation: '+report.outcome, mode=mode)


def run_cli(args):
    usage = 'OpenAI API usage' if args.agent == 'openai' else 'Codex account usage' if args.agent == 'codex' else 'no model usage in replay mode'
    print('Checking prerequisites; ' + usage + '.', file=sys.stderr)
    try:
        if args.agent == 'codex': agent = CodexAgent(model=args.model)
        elif args.agent == 'openai': agent = OpenAIAgent(model=args.model)
        else:
            with Path(args.responses).open('rb') as stream: raw = stream.read(3145729)
            if len(raw) > 3145728: raise InvestigationError('RESPONSES_LIMIT', 'options', 'response file exceeds 3 MiB')
            responses = parse_json(raw)
            if type(responses) is not list or not 1 <= len(responses) <= 3:
                raise InvestigationError('RESPONSES_FORMAT', 'options', 'response file must be an array of one to three decisions')
            agent = RecordedAgent(tuple(canonical_json(value) for value in responses))
        report = run_investigation(InvestigationOptions(Path(args.case_dir), args.scenario, args.hint, args.max_rounds), agent, DockerVerifier())
    except (InvestigationError, ProvenanceError, OSError) as error:
        code = error.code if isinstance(error, InvestigationError) else error.problem.code if isinstance(error, ProvenanceError) else 'IO_ERROR'
        report = InvestigationReport('ERROR', args.agent, args.agent != 'recorded', str(Path(args.case_dir).absolute()), args.scenario,
                                     error={'code': code, 'stage': 'options', 'detail': str(error)[:2000]}, reason=str(error)[:2000])
    text = render_report(report)
    # Only a case actually created by this invocation can receive output files.
    if report.evidence and Path(report.case_dir).is_dir():
        try: safe_path(Path(report.case_dir), 'report.md').write_text(text, encoding='utf-8', newline='\n')
        except (InvestigationError, OSError) as error:
            report.outcome = 'ERROR'
            report.error = {'code': getattr(error, 'code', 'IO_ERROR'), 'stage': 'report', 'detail': str(error)[:2000]}
            report.reason = report.error['detail']
            text = render_report(report)
            try:
                safe_path(Path(report.case_dir), 'report.json').write_bytes(canonical_json(report.as_dict()))
                safe_path(Path(report.case_dir), 'error.json').write_bytes(canonical_json(report.error))
            except (InvestigationError, OSError): pass
    output = canonical_json(report.as_dict()) + b'\n' if args.json else text.encode('utf-8')
    if hasattr(sys.stdout, 'buffer'): sys.stdout.buffer.write(output)
    else: sys.stdout.write(output.decode('utf-8'))
    if report.error and report.error['stage'] == 'options': return 2
    return {'ACCEPTED': 0, 'REFUSED': 3, 'UNRESOLVED': 4, 'ERROR': 1}[report.outcome]
