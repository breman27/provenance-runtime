"""Shared, record-typed reports for any client of the provenance runtime."""
import html
import json
import re
from collections import defaultdict
from datetime import datetime, timezone

from .format import parse_json, utc_timestamp
from .projection import status

KINDS = ('Observation', 'Claim', 'ProposedAction', 'Verification', 'Authority', 'Effect', 'Invalidation', 'Supersession')
HEADINGS = {'Observation': 'Evidence — Observations', 'Claim': 'Claims', 'ProposedAction': 'ProposedActions',
            'Verification': 'Verifications', 'Authority': 'Authorities', 'Effect': 'Effects',
            'Invalidation': 'Invalidations', 'Supersession': 'Supersessions'}
PREFIXES = dict(zip(KINDS, ('O', 'C', 'P', 'V', 'A', 'E', 'I', 'S')))


def snapshot_records(store, roots, aliases=None):
    """Capture actual record kinds/links and their execution status in one read snapshot.

    Also include checks/grants/effects for requested proposals, even when a gate
    refused them, and applicable later controls. Historical outcomes stay separate.
    """
    aliases = aliases or {}
    with store.read_snapshot():
        included = set()
        pending = list(set(roots))
        while pending:
            node_id = pending.pop()
            if node_id in included:
                continue
            validation = store.validate(node_id)
            if not validation.ok:
                from .errors import ProvenanceError
                raise ProvenanceError(validation.errors[0])
            added = set(validation.visited) - included
            included.update(validation.visited)
            for identifier in added:
                node = store.get(identifier)
                for child_id in store.child_ids(identifier):
                    child = store.get(child_id)
                    check_for_action = node.kind == 'ProposedAction' and child.kind in ('Verification', 'Authority', 'Effect')
                    later_control = child.kind in ('Invalidation', 'Supersession') and any(
                        parent.role == 'target' and parent.node_id == identifier for parent in child.parents)
                    if check_for_action or later_control:
                        pending.append(child_id)
        by_id = defaultdict(list)
        for alias, identifier in aliases.items():
            by_id[identifier].append(alias)
        nodes = sorted((store.get(identifier) for identifier in included), key=lambda node: (node.created_at, node.id))
        admissions = {node.id: store.admission(node.id) for node in nodes}
        return {'format': 'provenance-report-records', 'version': '0.1',
                'captured_at': utc_timestamp(datetime.now(timezone.utc)),
                'records': [{'id': node.id, 'body': parse_json(node.canonical_body),
                             'status': status(store, node.id, 'execution'),
                             'aliases': sorted(by_id[node.id]),
                             'admission': ({'operation': admissions[node.id].operation, 'principal_id': admissions[node.id].principal_id}
                                           if admissions[node.id] else None)} for node in nodes]}


def _text(value):
    text = html.escape(str(value), quote=False).replace('\r', ' ').replace('\n', ' ')
    return text.replace('|', '\\|')


def _code(value):
    value = str(value)
    longest = max((len(match) for match in re.findall(r'`+', value)), default=0)
    delimiter = '`' * (longest + 1)
    return delimiter + ' ' + value + ' ' + delimiter if longest else delimiter + value + delimiter


def _block(value, language=''):
    value = str(value)
    longest = max((len(match) for match in re.findall(r'`+', value)), default=0)
    delimiter = '`' * max(3, longest + 1)
    return [delimiter+language, value.rstrip('\n'), delimiter]


def _quote(value):
    return ['> '+_text(line) for line in str(value).splitlines()]


def _observation_summary(payload):
    if type(payload.get('entries')) is list:
        entries = payload['entries']
        pairs = [f"{entry['input']} → {entry['output']}" for entry in entries
                 if type(entry) is dict and 'input' in entry and 'output' in entry]
        if pairs:
            return 'Recorded inputs → outputs: ' + ', '.join(pairs)
    keys = ('source', 'revision', 'suite', 'outcome', 'tests_run', 'failures', 'errors',
            'reported_statement', 'message', 'stderr')
    values = [(key, payload[key]) for key in keys if key in payload and type(payload[key]) in (str, int, bool)]
    if not values:
        values = [(key, value) for key, value in payload.items() if type(value) in (str, int, bool)][:4]
    return '; '.join(f'{key}: {str(value)[:240]}' for key, value in values) or 'Captured data; see the record payload.'


def render_record_report(snapshot, *, title='Provenance report', context=(), outcome=None, reason='',
                         fallback=None, notes=(), activity=()):
    """Render a consistent vocabulary, actual IDs, and explicit parent relationships.

    `fallback` is only summary text from legacy report envelopes lacking record
    bodies. It never promotes a raw test result into a Verification record.
    """
    snapshot = snapshot or {'records': []}
    records = snapshot['records']
    fallback = fallback or {}
    counts = defaultdict(int)
    labels, anchors, descriptions = {}, {}, {}
    for record in records:
        kind = record['body']['kind']
        counts[kind] += 1
        label = kind + ' ' + PREFIXES[kind] + str(counts[kind])
        labels[record['id']] = label
        anchors[record['id']] = kind.lower()+'-'+PREFIXES[kind].lower()+str(counts[kind])
        descriptions[record['id']] = label + (' — '+', '.join(record['aliases']) if record.get('aliases') else '')
    children = defaultdict(list)
    for record in records:
        for parent in record['body']['parents']:
            children[parent['id']].append((record['id'], parent['role']))
    def reference(identifier):
        if identifier not in labels:
            return _code(identifier)
        return '['+_text(descriptions[identifier])+'](#'+anchors[identifier]+')'
    lines = ['# '+title, '']
    for item in context:
        lines.extend([str(item), ''])
    if snapshot.get('captured_at'):
        lines.extend(['Record statuses captured at: '+_code(snapshot['captured_at']),
                      'Outcome is the recorded run result. Status describes justification at the snapshot time.', ''])
    if not records and any(fallback.values()):
        lines.extend(['Record bodies are unavailable in this envelope; the references below are report summaries.', ''])
    lines.extend(['Evidence → Claim → ProposedAction; Verification and Authority support admission of an Effect.', ''])
    for kind in KINDS:
        group = [record for record in records if record['body']['kind'] == kind]
        if kind in ('Invalidation', 'Supersession') and not group:
            continue
        lines.extend(['## '+HEADINGS[kind], ''])
        if kind == 'Observation':
            lines.extend(['Captured inputs and tool results. Evidence links under each Claim and Verification identify their supporting records.', ''])
        if kind == 'Observation' and group:
            lines.extend(['| Record | Captured data | Status |', '| --- | --- | --- |'])
            for record in group:
                lines.append('| '+reference(record['id'])+' | '+_text(_observation_summary(record['body']['payload']))+' | '+record['status']+' |')
            lines.append('')
        if not group:
            lines.extend(fallback.get(kind) or ['No '+kind+' record is present in this report.'])
            lines.append('')
            continue
        for record in group:
            body, identifier = record['body'], record['id']
            payload = body['payload']
            if kind == 'Observation':
                lines.extend(['<a id="'+anchors[identifier]+'"></a>', '<details>',
                              '<summary>'+_text(descriptions[identifier])+' — record details</summary>', ''])
            else:
                lines.extend(['<a id="'+anchors[identifier]+'"></a>', '### '+_text(descriptions[identifier]), ''])
            lines.extend([
                          'Record ID: '+_code(identifier),
                          'Status: **'+_text(record['status'])+'** · Producer: '+_code(body['producer']), ''])
            if kind in ('Observation','Verification','Authority','Effect','Invalidation','Supersession'):
                admission = record.get('admission')
                lines.extend(['Local admission: '+(_code(admission['operation'])+' by '+_code(admission['principal_id']) if admission else 'none recorded'), ''])
            if kind == 'Observation':
                lines.extend([_text(_observation_summary(payload)), ''])
                if payload.get('source_text'):
                    lines.extend(_block(payload['source_text'], 'python'))
                    lines.append('')
                if payload.get('readme'):
                    lines.extend(_quote(payload['readme']))
                    lines.append('')
            elif kind == 'Claim':
                lines.extend(_quote(payload['statement']))
                lines.append('')
                if payload.get('summary') and payload['summary'] != payload['statement']:
                    lines.extend(['Summary: '+_text(payload['summary']), ''])
            elif kind == 'ProposedAction':
                lines.extend(['Action type: '+_code(payload['action_type']),
                              'Resource: '+_code(payload['resource']), ''])
                arguments = payload['arguments']
                if type(arguments.get('patch_content')) is str:
                    lines.extend(['Proposed replacement for '+_code(arguments.get('target_path', 'target'))+':', ''])
                    lines.extend(_block(arguments['patch_content'], 'python'))
                    lines.append('')
            elif kind == 'Verification':
                lines.extend(['Check: '+_code(payload['check']),
                              'Check result: **'+('PASS' if payload['passed'] else 'FAIL')+'**', ''])
            elif kind == 'Authority':
                lines.extend(['Permission: **'+('ALLOW' if payload['allowed'] else 'DENY')+'**',
                              'Expires at: '+_code(payload['expires_at']),
                              'Issuer: '+_code(payload['issuer_id']), ''])
            elif kind == 'Effect':
                lines.extend(['Receipt: '+_code(payload['receipt'].get('kind', 'recorded effect')), ''])
            elif kind in ('Invalidation', 'Supersession'):
                lines.extend([_text(payload['reason']), ''])
            parents = defaultdict(list)
            for parent in body['parents']:
                parents[parent['role']].append(reference(parent['id']))
            for role, references in parents.items():
                lines.append(role.replace('_',' ').capitalize()+': '+', '.join(references))
            if children[identifier]:
                lines.append('Referenced by: '+', '.join(reference(child)+' ('+role+')' for child,role in children[identifier]))
            if kind == 'Observation':
                lines.extend(['', 'Full record payload:', ''])
            else:
                lines.extend(['', '<details>', '<summary>Full record payload</summary>', ''])
            lines.extend(_block(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), 'json'))
            lines.extend(['', '</details>', ''])
    lines.extend(['## Outcome', '', '**'+_text(outcome or 'UNREPORTED')+'**', '', _text(reason), ''])
    if notes:
        lines.extend(['## Context and controls', '', *notes, ''])
    if activity:
        lines.extend(['## Tool and check activity', '', *activity, ''])
    return '\n'.join(lines).rstrip()+'\n'
