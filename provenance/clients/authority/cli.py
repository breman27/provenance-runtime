"""Local operator commands; no agent imports, key lookup or inference."""
import sqlite3
import sys

from ...errors import ProvenanceError
from ...format import canonical_json
from ..repo_repair.errors import InvestigationError
from ..repo_repair.case import safe_path
from .manager import ApprovalManager
from .context import open_session, load_context, write_object
from ...store import Store
from .report import render_authority_report


def _output(value, text, machine):
    data = canonical_json(value)+b'\n' if machine else text.encode('utf-8')
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout.buffer.write(data)
    else:
        sys.stdout.write(data.decode('utf-8'))


def _save(root, result):
    session = open_session(root)
    with Store(session.database) as store:
        ctx = load_context(session, store, result.action_id, artifacts=False)
    case_dir = safe_path(session.root, ctx.data['case_dir'])
    write_object(case_dir, 'authority-report.json', result.as_dict())
    safe_path(case_dir, 'authority-report.md').write_text(render_authority_report(result), encoding='utf-8', newline='\n')


def run_cli(args):
    result = None
    try:
        manager = ApprovalManager(args.session_dir)
        command = args.authority_command
        if command == 'list':
            results = manager.list(include_all=args.include_all)
            text = '\n'.join(r.state+'  '+r.action_id for r in results)+'\n' if results else 'No matching proposals.\n'
            _output([r.as_dict() for r in results], text, args.json)
            return 0
        if command == 'inspect':
            result = manager.inspect(args.action)
        elif command == 'approve':
            result = manager.approve(args.action, args.ttl_minutes, args.reason, args.renew)
        elif command == 'deny':
            result = manager.deny(args.action, args.reason)
        elif command == 'revoke':
            result = manager.revoke(args.authority, args.reason)
        else:
            result = manager.admit(args.action)
        if command != 'inspect':
            try:
                _save(args.session_dir, result)
            except (OSError, InvestigationError, ProvenanceError, sqlite3.Error) as error:
                _output({'error': {'code': 'REPORT_WRITE', 'detail': 'Decision/result is retained but the report could not be saved.'},
                         'result': result.as_dict()}, 'REPORT_WRITE: Result is retained; report could not be saved.\n'+render_authority_report(result), args.json)
                return 1
        _output(result.as_dict(), render_authority_report(result), args.json)
        return 3 if command == 'admit' and result.state != 'COMMITTED' else 0
    except (InvestigationError, ProvenanceError, OSError, sqlite3.Error) as error:
        code = error.code if isinstance(error, InvestigationError) else error.problem.code if isinstance(error, ProvenanceError) else 'IO_ERROR'
        detail = error.detail if isinstance(error, InvestigationError) else error.problem.detail if isinstance(error, ProvenanceError) else str(error)[:1000]
        _output({'error': {'code': code, 'detail': detail}}, code+': '+detail+'\n', args.json)
        if code == 'OPTIONS':
            return 2
        return 3 if args.authority_command == 'admit' and code in ('STALE', 'VERIFICATION_FAILED', 'AUTHORITY_EXPIRED', 'AUTHORITY_REVOKED', 'AUTHORITY_DENIED') else 1
