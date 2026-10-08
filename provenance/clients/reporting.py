"""Adapter shared by all investigation clients; headings come from runtime kinds."""
from ..reporting import snapshot_records, render_record_report, _code


def report_record_snapshot(store, report):
    roots = set(report.get('evidence', {}).values())
    for row in (report, report.get('old_action') or {}, *report.get('rounds', []), *report.get('tests', [])):
        roots.update(row[key] for key in ('claim_id','action_id','authority_id','effect_id','observation_id','verification_id') if row.get(key))
    return snapshot_records(store, roots, report.get('evidence', {}))


def render_investigation_report(report, *, title, mode):
    fallback = {kind: [] for kind in ('Observation','Claim','ProposedAction','Verification','Authority','Effect')}
    for alias, identifier in report.get('evidence', {}).items():
        fallback['Observation'].append('- Observation '+_code(alias)+': '+_code(identifier))
    rounds = report.get('rounds', [])
    if report.get('decision'):
        rounds = [dict(report['decision'], claim_id=report.get('claim_id'), action_id=report.get('action_id'))]
    for row in rounds:
        if row.get('claim_id'):
            fallback['Claim'].extend(['### Claim '+_code(row['claim_id']), '', row['claim_statement'], '',
                'Evidence aliases: '+', '.join(_code(alias) for alias in row.get('evidence_aliases', [])), ''])
        if row.get('action_id'):
            fallback['ProposedAction'].extend(['ProposedAction: '+_code(row['action_id']), ''])
    for kind, key in (('Authority','authority_id'),('Effect','effect_id')):
        if report.get(key):
            fallback[kind].append(kind+': '+_code(report[key]))
    notes = []
    if report.get('human_hint'):
        notes.append('Human report: '+report['human_hint'])
    if report.get('old_action'):
        old = report['old_action']
        notes.append('Earlier ProposedAction: '+old['gate_outcome']+'; justification status: '+str(old.get('status')))
        if old.get('reason'):
            notes.append(old['reason'])
    if report.get('error'):
        notes.append('Error: '+report['error']['code']+' at '+report['error']['stage'])
    if report.get('record_snapshot_error'):
        notes.append('Record snapshot unavailable: '+report['record_snapshot_error']['code'])
    activity = ['- Step '+str(step['step'])+': '+_code(step['tool'])+' (tool operation)' for step in report.get('steps', [])]
    for test in report.get('tests', []):
        activity.append('- '+test.get('phase','check')+' / '+_code(test['suite'])+': '+test['outcome'].upper()+
                        ' — '+str(test['tests_run'])+' tests, '+str(test.get('failures',0))+' failures, '+str(test.get('errors',0))+' errors (check output)')
    return render_record_report(report.get('record_snapshot'), title=title,
        context=[mode, 'Case: '+report['case_dir'], 'Scenario: '+report['scenario']],
        outcome=report['outcome'], reason=report.get('reason',''), fallback=fallback, notes=notes, activity=activity)
