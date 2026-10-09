"""Readable permission projection over actual immutable record types."""
import difflib

from ...reporting import render_record_report, _block, _code, _text


def render_authority_report(result):
    records = {r['id']: r for r in result.record_snapshot['records']}
    action = records[result.action_id]
    context = next(r['body']['payload']['context'] for r in records.values()
                   if r['body']['kind'] == 'Observation' and r['body']['payload'].get('source') == 'approval-context')
    source = records[context['source_observation_id']]['body']['payload']['source_text']
    candidate = action['body']['payload']['arguments']['patch_content']
    diff = ''.join(difflib.unified_diff(source.splitlines(keepends=True), candidate.splitlines(keepends=True),
                                      fromfile='before/'+context['target_path'], tofile='proposed/'+context['target_path']))
    notes = ['Application permission state: '+result.state,
             'Runtime justification status: '+action['status'],
             'Source freshness is probed before approval/admission; inspection shows recorded status.',
             'Actor human-operator is a local audit role; it does not authenticate a physical human.',
             'Existing effects are simulated local receipts; no source patch is applied.']
    body = render_record_report(result.record_snapshot, title='Human authority review',
        context=['Action: '+result.action_id, 'Baseline: '+context['baseline_revision'],
                 'Candidate snapshot: '+context['candidate_snapshot'], 'Pinned verifier image: '+context['image_id']],
        outcome=result.state, reason=result.reason, notes=notes)
    lines = [body.rstrip(), '', '## Exact proposed diff', '', *_block(diff, 'diff'), '', '## Operator decision history', '']
    grants = [r for r in records.values() if r['body']['kind'] == 'Authority'
              and r['body']['producer'] == 'human-operator'
              and r.get('admission') == {'principal_id': 'human-operator', 'operation': 'authorize'}
              and type(r['body']['payload'].get('decision')) is dict]
    for row in sorted(grants, key=lambda r: r['body']['payload']['decision'].get('sequence', 0)):
        payload = row['body']['payload']
        metadata = payload['decision']
        lines += ['- '+_code(row['id'])+'; sequence '+_text(metadata['sequence'])+'; allowed '+str(payload['allowed'])+
                  '; expires '+_code(payload['expires_at'])+'; status '+row['status'],
                  '  Reason: '+_text(metadata.get('reason') or '(none)'), '']
    if not grants:
        lines += ['No operator decision has been recorded.', '']
    return '\n'.join(lines)+'\n'
