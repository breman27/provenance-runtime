"""Readable investigation reports and CLI boundary."""
import sys
from pathlib import Path
from ...errors import ProvenanceError
from ...format import canonical_json, parse_json
from .agent import CodexAgent, RecordedAgent
from .coordinator import InvestigationOptions, InvestigationReport, run_investigation
from .errors import InvestigationError
from .verifier import DockerVerifier


def _short(node_id): return node_id[:19] + '…' if node_id else 'none'


def render_report(report):
    mode = 'Live Codex reasoning' if report.live_agent else 'Recorded reasoning (replay; no live model call)'
    lines = [f'# Investigation: {report.outcome}', '', mode, '', f'Case: {report.case_dir}',
             f'Scenario: {report.scenario}', '', 'Sources captured:']
    for source in report.sources:
        lines.append(f'- Observation `{source["alias"]}`: Git revision `{source["revision"]}`, snapshot `{source["snapshot_hash"]}`')
    if not report.sources: lines.append('- No source capture completed.')
    for row in report.rounds:
        lines.extend(['', f'## Round {row["round"]}: CLAIMED', '', row['claim_statement'], '', row['summary'],
                      f'Claim: {_short(row["claim_id"])}'])
        if row.get('evidence_aliases'): lines.append('Evidence: ' + ', '.join(row['evidence_aliases']))
        if row['action_id']:
            lines.extend([f'ProposedAction: {_short(row["action_id"])}', '', '```diff', row.get('diff', '').rstrip(), '```'])
        else: lines.append('No changed candidate proposed.')
        if row['round'] == 1 and report.human_hint:
            lines.extend(['', '## Human contribution', '', report.human_hint, '', 'Recorded as a report to investigate.'])
    if report.old_action:
        old = report.old_action
        lines.extend(['', f'Earlier proposal: {old["gate_outcome"]}; status {old["status"] or "no action"}.'])
        if old.get('reason'): lines.append(old['reason'])
    lines.extend(['', '## TESTED', ''])
    for test in report.tests:
        lines.append(f'- {test["phase"]} / {test["suite"]}: {test["outcome"].upper()} — {test["tests_run"]} tests, '
                     f'{test["failures"]} failures, {test["errors"]} errors; {test["elapsed_ms"]} ms')
    if not report.tests: lines.append('No candidate code was tested.')
    lines.extend(['', f'## {report.outcome}', '', report.reason])
    if report.error: lines.append(f'Error: {report.error["code"]} at {report.error["stage"]}')
    if report.effect_id:
        lines.extend([f'Effect receipt: {report.effect_id}', f'Authority: {report.authority_id}',
                      'The receipt records simulated local acceptance. Test results support the supplied cases.'])
    if report.evidence:
        lines.extend(['', '## Provenance references', ''])
        lines.extend(f'- Observation `{alias}`: `{node_id}`' for alias, node_id in report.evidence.items())
    return '\n'.join(lines) + '\n'


def run_cli(args):
    print('Checking prerequisites; live mode consumes normal Codex account usage when invoked.', file=sys.stderr)
    try:
        if args.agent == 'codex': agent = CodexAgent(model=args.model)
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
        report = InvestigationReport('ERROR', args.agent, args.agent == 'codex', str(Path(args.case_dir).absolute()), args.scenario,
                                     error={'code': code, 'stage': 'options', 'detail': str(error)[:2000]}, reason=str(error)[:2000])
    text = render_report(report)
    # Only a case actually created by this invocation can receive output files.
    if report.evidence and Path(report.case_dir).is_dir():
        (Path(report.case_dir) / 'report.md').write_text(text, encoding='utf-8', newline='\n')
    print(canonical_json(report.as_dict()).decode('utf-8') if args.json else text, end='\n' if args.json else '')
    if report.error and report.error['stage'] == 'options': return 2
    return {'ACCEPTED': 0, 'REFUSED': 3, 'UNRESOLVED': 4, 'ERROR': 1}[report.outcome]
