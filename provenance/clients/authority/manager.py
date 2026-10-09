"""Durable local operator decisions and exact-action simulated admission."""
from contextlib import contextmanager
from dataclasses import dataclass, asdict, replace
from datetime import datetime, timedelta, timezone

from ...errors import ProvenanceError
from ...format import canonical_json, utc_timestamp
from ...projection import status
from ...reporting import snapshot_records
from ...runtime import Runtime
from ...store import Store, Admission
from ..repo_repair.errors import fail
from .context import open_session, load_context, content_id
from .profiles import authority_policy
from .lock import session_lock
from .resources import check_current


def utc_now():
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ApprovalResult:
    action_id: str
    state: str
    authority_id: str | None
    effect_id: str | None
    reused: bool
    reason: str
    integrity_ok: bool
    record_snapshot: dict

    def as_dict(self):
        return asdict(self)


def _reason(value):
    if value == '':
        value = None
    if value is not None and (type(value) is not str or len(value) > 4000):
        fail('OPTIONS', 'authority', 'reason must be text of at most 4,000 characters')
    try:
        canonical_json(value)
    except ProvenanceError:
        fail('OPTIONS', 'authority', 'reason must be valid Unicode text')
    return value


class ApprovalManager:
    def __init__(self, session_dir, *, clock=utc_now):
        self.root, self.clock = session_dir, clock

    @contextmanager
    def _operation(self, *, mutation=False):
        try:
            session = open_session(self.root)
            if session.mode != 'manual':
                fail('APPROVAL_MODE', 'authority', 'operator commands require a manual session')
            @contextmanager
            def opened():
                # Revalidate after acquiring the operator lock, before opening our connection.
                current = open_session(session.root)
                if current != session:
                    fail('APPROVAL_SESSION', 'authority', 'session changed during operation')
                with Store(session.database) as store:
                    yield session, Runtime(store, authority_policy('manual'), self.clock)
            if mutation:
                with session_lock(session), opened() as pair:
                    yield pair
            else:
                with opened() as pair:
                    yield pair
        except ProvenanceError as error:
            fail(error.problem.code, 'authority', error.problem.detail)

    def _decisions(self, runtime, ctx):
        store, action_id = runtime.store, ctx.action_id
        action = store.get(action_id)
        decisions = []
        sequences = set()
        for node_id in store.child_ids(action_id):
            node = store.get(node_id)
            if node.kind != 'Authority' or store.admission(node_id) != Admission('human-operator', 'authorize'):
                continue
            report = store.validate(node_id)
            payload, metadata = node.payload, node.payload.get('decision')
            if (not report.ok or node.producer != 'human-operator'
                    or [p.node_id for p in node.parents if p.role == 'subject'] != [action_id]
                    or payload['issuer_id'] != 'human-operator' or payload['subject'] != runtime.policy.subject
                    or payload['action_id'] != action_id or payload['action_type'] != action.payload['action_type']
                    or payload['resource'] != action.payload['resource'] or type(metadata) is not dict
                    or set(metadata) != {'method', 'actor', 'context_hash', 'sequence', 'reason', 'ttl_minutes'}
                    or metadata['method'] != 'local-cli' or metadata['actor'] != 'human-operator'
                    or metadata['context_hash'] != ctx.context_hash or type(metadata['sequence']) is not int
                    or not 1 <= metadata['sequence'] <= 2**53-1
                    or metadata['sequence'] in sequences
                    or (payload['allowed'] and (type(metadata['ttl_minutes']) is not int or not 1 <= metadata['ttl_minutes'] <= 60))
                    or (not payload['allowed'] and metadata['ttl_minutes'] is not None)):
                fail('DECISION_INTEGRITY', 'authority', 'manual decision history has inconsistent scope or sequence')
            _reason(metadata['reason'])
            sequences.add(metadata['sequence'])
            decisions.append(node)
        return sorted(decisions, key=lambda node: node.payload['decision']['sequence'])

    @staticmethod
    def _has_control(runtime, target, kind):
        for node_id in runtime.store.child_ids(target):
            node = runtime.store.get(node_id)
            if (node.kind == kind and runtime.store.admission(node_id) == Admission('controller', 'control')
                    and node.producer == 'controller' and any(p.role == 'target' and p.node_id == target for p in node.parents)):
                report = runtime.store.validate(node_id)
                if not report.ok:
                    fail('DECISION_INTEGRITY', 'authority', 'decision control is corrupt')
                return True
        return False

    def _reconcile(self, runtime, ctx):
        decisions = self._decisions(runtime, ctx)
        if len(decisions) < 2:
            return decisions
        controller, latest = runtime.controller('controller'), decisions[-1]
        for index, older in enumerate(decisions[:-1]):
            later_denial = any(not n.payload['allowed'] for n in decisions[index+1:])
            if older.payload['allowed'] and later_denial and not self._has_control(runtime, older.id, 'Invalidation'):
                runtime.invalidate(controller, older.id, 'permission withdrawn by a later explicit denial')
            if not self._has_control(runtime, older.id, 'Supersession'):
                runtime.supersede(controller, older.id, latest.id, 'replaced by a later operator decision')
        return decisions

    def _result(self, session, runtime, ctx, *, reused=False, reason=None):
        receipt = runtime.local_receipt(ctx.action_id)
        if receipt is not None and not receipt.integrity.ok:
            fail('RECEIPT_INTEGRITY', 'authority', 'existing local receipt mapping or ancestry is corrupt')
        decisions = self._decisions(runtime, ctx)
        latest = decisions[-1] if decisions else None
        authority_id = latest.id if latest else None
        if receipt is not None:
            state, message = 'COMMITTED', 'Historical local receipt; current record status is shown separately.'
        elif status(runtime.store, ctx.action_id, 'execution') != 'VALID' or status(runtime.store, ctx.observation_id, 'execution') != 'VALID':
            state, message = 'STALE', 'Proposal or supporting justification is unusable.'
        elif any(status(runtime.store, i, 'execution') != 'VALID' for i in ctx.data['verification_ids']):
            state, message = 'VERIFICATION_FAILED', 'Required verification is unusable.'
        elif latest is None:
            state, message = 'AWAITING_APPROVAL', 'Verified proposal awaits a local operator decision.'
        elif not latest.payload['allowed']:
            state, message = 'DENIED', 'Latest operator decision denies permission.'
        elif status(runtime.store, latest.id, 'execution') in ('INVALID', 'SUPERSEDED'):
            state, message = 'REVOKED', 'Current grant has been withdrawn.'
        elif status(runtime.store, latest.id, 'execution') != 'VALID':
            state, message = 'STALE', 'Permission justification is unusable.'
        elif utc_timestamp(runtime.clock()) >= latest.payload['expires_at']:
            state, message = 'EXPIRED', 'Current grant expired; explicit approval is required.'
        else:
            state, message = 'APPROVED', 'Permission is active; admission is a separate operation.'
        roots = [ctx.action_id, ctx.observation_id, session.observation_id]
        if receipt:
            roots.append(receipt.effect_id)
        snapshot = snapshot_records(runtime.store, roots)
        return ApprovalResult(ctx.action_id, state, authority_id, receipt.effect_id if receipt else None,
                              reused, reason or message, True, snapshot)

    def list(self, include_all=False):
        with self._operation() as (session, runtime):
            actions = set()
            for node_id in runtime.store.all_ids():
                node = runtime.store.get(node_id)
                data = node.payload.get('context')
                if (node.kind == 'Observation' and node.payload.get('source') == 'approval-context'
                        and type(data) is dict and data.get('session_id') == session.session_id
                        and runtime.store.admission(node_id) == Admission('collector', 'observe')):
                    actions.add(content_id(data.get('action_id')))
            results = []
            for action_id in sorted(actions):
                ctx = load_context(session, runtime.store, action_id, artifacts=False)
                result = self._result(session, runtime, ctx)
                if include_all or result.state in ('AWAITING_APPROVAL', 'APPROVED', 'EXPIRED', 'REVOKED'):
                    results.append(result)
            return tuple(results)

    def inspect(self, action_id):
        with self._operation() as (session, runtime):
            ctx = load_context(session, runtime.store, action_id, artifacts=False)
            return self._result(session, runtime, ctx)

    @staticmethod
    def _eligible(runtime, ctx):
        if status(runtime.store, ctx.action_id, 'execution') != 'VALID' or status(runtime.store, ctx.observation_id, 'execution') != 'VALID':
            fail('STALE', 'authority', 'proposal or supporting justification is unusable')
        if any(status(runtime.store, i, 'execution') != 'VALID' for i in ctx.data['verification_ids']):
            fail('VERIFICATION_FAILED', 'authority', 'required verification is unusable')

    def approve(self, action_id, ttl_minutes=15, reason=None, renew=False):
        reason = _reason(reason)
        if type(ttl_minutes) is not int or not 1 <= ttl_minutes <= 60 or type(renew) is not bool:
            fail('OPTIONS', 'authority', 'approval TTL must be an integer from 1 to 60; renew must be boolean')
        with self._operation(mutation=True) as (session, runtime):
            ctx = load_context(session, runtime.store, action_id)
            decisions = self._reconcile(runtime, ctx)
            if runtime.local_receipt(action_id) is not None:
                return replace(self._result(session, runtime, ctx, reused=True), state='ALREADY_COMMITTED')
            check_current(session, runtime, ctx)
            self._eligible(runtime, ctx)
            result = self._result(session, runtime, ctx)
            if result.state == 'APPROVED' and not renew:
                metadata = decisions[-1].payload['decision']
                if (metadata['reason'], metadata['ttl_minutes']) != (reason, ttl_minutes):
                    fail('RENEW_REQUIRED', 'authority', 'changing an active approval reason or TTL requires --renew')
                return replace(result, reused=True)
            sequence = decisions[-1].payload['decision']['sequence']+1 if decisions else 1
            metadata = {'method': 'local-cli', 'actor': 'human-operator', 'context_hash': ctx.context_hash,
                        'sequence': sequence, 'reason': reason, 'ttl_minutes': ttl_minutes}
            runtime.authorize(runtime.issuer('human-operator'), action_id, True,
                              runtime.clock()+timedelta(minutes=ttl_minutes), decision=metadata)
            self._reconcile(runtime, ctx)
            return self._result(session, runtime, ctx)

    def deny(self, action_id, reason=None):
        reason = _reason(reason)
        with self._operation(mutation=True) as (session, runtime):
            ctx = load_context(session, runtime.store, action_id, artifacts=False)
            decisions = self._reconcile(runtime, ctx)
            result = self._result(session, runtime, ctx)
            if result.effect_id:
                return replace(result, state='ALREADY_COMMITTED', reused=True,
                               reason='Receipt already exists; revoke its grant to record withdrawal.')
            if decisions and not decisions[-1].payload['allowed'] and decisions[-1].payload['decision']['reason'] == reason:
                return replace(result, reused=True)
            sequence = decisions[-1].payload['decision']['sequence']+1 if decisions else 1
            metadata = {'method': 'local-cli', 'actor': 'human-operator', 'context_hash': ctx.context_hash,
                        'sequence': sequence, 'reason': reason, 'ttl_minutes': None}
            runtime.authorize(runtime.issuer('human-operator'), action_id, False,
                              runtime.clock(), decision=metadata)
            self._reconcile(runtime, ctx)
            return self._result(session, runtime, ctx)

    def revoke(self, authority_id, reason=None):
        reason = _reason(reason)
        with self._operation(mutation=True) as (session, runtime):
            node = runtime.store.get(content_id(authority_id))
            if node.kind != 'Authority':
                fail('AUTHORITY_SCOPE', 'authority', 'revocation requires an in-session Authority ID')
            ctx = load_context(session, runtime.store, node.payload['action_id'], artifacts=False)
            decisions = self._reconcile(runtime, ctx)
            if authority_id not in {d.id for d in decisions} or not node.payload['allowed']:
                fail('AUTHORITY_SCOPE', 'authority', 'only a locally issued allowed grant can be revoked')
            reused = self._has_control(runtime, authority_id, 'Invalidation')
            if not reused:
                runtime.invalidate(runtime.controller('controller'), authority_id, reason or 'operator revoked permission')
            return self._result(session, runtime, ctx, reused=reused)

    def admit(self, action_id):
        with self._operation(mutation=True) as (session, runtime):
            ctx = load_context(session, runtime.store, action_id, artifacts=False)
            self._reconcile(runtime, ctx)
            result = self._result(session, runtime, ctx)
            if result.effect_id:
                return replace(result, reused=True)
            ctx = load_context(session, runtime.store, action_id)
            check_current(session, runtime, ctx)
            result = self._result(session, runtime, ctx)
            if result.state != 'APPROVED':
                return result
            try:
                receipt = runtime.commit(action_id, tuple(ctx.data['verification_ids']), result.authority_id)
            except ProvenanceError as error:
                return self._result(session, runtime, ctx, reason=error.problem.code+': '+error.problem.detail)
            if not receipt.integrity.ok:
                fail('RECEIPT_INTEGRITY', 'authority', 'gate returned a corrupt receipt')
            return self._result(session, runtime, ctx, reused=receipt.reused)
