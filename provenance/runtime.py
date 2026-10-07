"""Trusted local handles admit records; producer labels grant no privileges.

This is an application boundary for model-controlled JSON, not a Python sandbox.
The host process and callers holding its handles are trusted.
"""
import hashlib
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Callable

from .errors import fail
from .format import canonical_json, utc_timestamp
from .model import Node, Parent, make_node
from .projection import check_supersession
from .store import Admission, Store


@dataclass(frozen=True)
class Policy:
    version: str
    subject: str
    observers: tuple[str, ...]
    verifiers: dict[str, tuple[str, ...]]
    issuers: tuple[str, ...]
    controllers: tuple[str, ...]
    requirements: dict[str, tuple[str, ...]]

    def __post_init__(self):
        def names(values):
            if not isinstance(values, (tuple, list)) or any(type(v) is not str or not v.strip() for v in values):
                fail("POLICY", "principal and check lists must contain nonempty strings")
            if len(set(values)) != len(values):
                fail("POLICY", "duplicate policy principal or check")
            return tuple(values)
        if any(type(v) is not str or not v.strip() for v in (self.version, self.subject)):
            fail("POLICY", "policy version and subject must be nonempty strings")
        for field in ("observers", "issuers", "controllers"):
            object.__setattr__(self, field, names(getattr(self, field)))
        for field in ("verifiers", "requirements"):
            value = getattr(self, field)
            if type(value) is not dict or any(type(k) is not str or not k.strip() for k in value):
                fail("POLICY", "policy check mappings need nonempty string keys")
            normalized = {k: names(v) for k, v in value.items()}
            if any(not checks for checks in normalized.values()):
                fail("POLICY", "verification requirements must not be empty")
            object.__setattr__(self, field, MappingProxyType(normalized))

    def snapshot(self) -> dict:
        return {"version": self.version, "subject": self.subject, "observers": list(self.observers),
                "verifiers": {k: list(v) for k, v in self.verifiers.items()}, "issuers": list(self.issuers),
                "controllers": list(self.controllers), "requirements": {k: list(v) for k, v in self.requirements.items()}}

    def content_hash(self) -> str:
        return "sha256:" + hashlib.sha256(canonical_json(self.snapshot())).hexdigest()


@dataclass(frozen=True, eq=False)
class ObserverHandle:
    principal_id: str


@dataclass(frozen=True, eq=False)
class VerifierHandle:
    principal_id: str


@dataclass(frozen=True, eq=False)
class AuthorityHandle:
    principal_id: str


@dataclass(frozen=True, eq=False)
class ControlHandle:
    principal_id: str


class Runtime:
    def __init__(self, store: Store, policy: Policy, clock: Callable[[], datetime]):
        self.store, self.policy, self.clock = store, policy, clock
        self._observers = {p: ObserverHandle(p) for p in policy.observers}
        self._verifiers = {p: VerifierHandle(p) for p in policy.verifiers}
        self._issuers = {p: AuthorityHandle(p) for p in policy.issuers}
        self._controllers = {p: ControlHandle(p) for p in policy.controllers}

    @staticmethod
    def _handle(registry, principal_id):
        if principal_id not in registry:
            fail("UNTRUSTED", "principal is not registered")
        return registry[principal_id]

    @staticmethod
    def _registered(registry, handle):
        principal_id = getattr(handle, "principal_id", None)
        if principal_id not in registry or registry[principal_id] is not handle:
            fail("UNTRUSTED", "handle was not issued by this runtime")
        return principal_id

    def observer(self, principal_id: str) -> ObserverHandle:
        return self._handle(self._observers, principal_id)

    def verifier(self, principal_id: str) -> VerifierHandle:
        return self._handle(self._verifiers, principal_id)

    def issuer(self, principal_id: str) -> AuthorityHandle:
        return self._handle(self._issuers, principal_id)

    def controller(self, principal_id: str) -> ControlHandle:
        return self._handle(self._controllers, principal_id)

    def submit(self, node: Node) -> str:
        return self.store.put(node)

    def _admit(self, kind, payload, parents, principal_id, operation):
        record = make_node(kind, payload, parents, principal_id, self.clock())
        with self.store.write_transaction():
            return self.store._insert(record, Admission(principal_id, operation))

    def observe(self, handle: ObserverHandle, payload: dict) -> str:
        principal = self._registered(self._observers, handle)
        return self._admit("Observation", payload, (), principal, "observe")

    def verify(self, handle: VerifierHandle, subject_id: str, check: str, passed: bool,
               evidence_ids: tuple[str, ...] = ()) -> str:
        principal = self._registered(self._verifiers, handle)
        if check not in self.policy.verifiers[principal]:
            fail("UNTRUSTED", "verifier is not registered for that check", subject_id)
        parents = [Parent("subject", subject_id)] + [Parent("evidence", i) for i in evidence_ids]
        return self._admit("Verification", {"verifier_id": principal, "check": check, "passed": passed},
                           parents, principal, "verify")

    def authorize(self, handle: AuthorityHandle, action_id: str, allowed: bool, expires_at: datetime) -> str:
        principal = self._registered(self._issuers, handle)
        action = self.store.get(action_id)
        if action.kind != "ProposedAction":
            fail("ILLEGAL_PARENT", "authority must bind a ProposedAction", action_id)
        payload = {"issuer_id": principal, "subject": self.policy.subject, "action_id": action_id,
                   "action_type": action.payload["action_type"], "resource": action.payload["resource"],
                   "allowed": allowed, "expires_at": utc_timestamp(expires_at)}
        return self._admit("Authority", payload, [Parent("subject", action_id)], principal, "authorize")

    def invalidate(self, handle: ControlHandle, target_id: str, reason: str) -> str:
        principal = self._registered(self._controllers, handle)
        return self._admit("Invalidation", {"reason": reason}, [Parent("target", target_id)], principal, "control")

    def supersede(self, handle: ControlHandle, target_id: str, replacement_id: str, reason: str) -> str:
        principal = self._registered(self._controllers, handle)
        record = make_node("Supersession", {"reason": reason},
                           [Parent("target", target_id), Parent("replacement", replacement_id)], principal, self.clock())
        with self.store.write_transaction():
            check_supersession(self.store, target_id, replacement_id)
            return self.store._insert(record, Admission(principal, "control"))

    def commit(self, action_id: str, verification_ids: tuple[str, ...], authority_id: str | None):
        from .gate import commit_effect
        return commit_effect(self, action_id, verification_ids, authority_id)
