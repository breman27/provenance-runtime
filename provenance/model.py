"""Immutable content-addressed records; creation time is part of identity."""
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .errors import fail
from .format import canonical_json, parse_json, utc_timestamp

DOMAIN = b"provenance-runtime:node:0.1\n"


@dataclass(frozen=True, order=True)
class Parent:
    role: str
    node_id: str


@dataclass(frozen=True)
class Node:
    id: str
    canonical_body: bytes

    def _body(self):
        return parse_json(self.canonical_body)

    @property
    def kind(self):
        return self._body()["kind"]

    @property
    def payload(self):
        return self._body()["payload"]

    @property
    def parents(self):
        return tuple(Parent(p["role"], p["id"]) for p in self._body()["parents"])

    @property
    def producer(self):
        return self._body()["producer"]

    @property
    def created_at(self):
        return self._body()["created_at"]

    @property
    def schema_version(self):
        return self._body()["schema_version"]


def content_id(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(DOMAIN + body).hexdigest()


def make_node(kind: str, payload: dict, parents: Iterable[Parent], producer: str,
              created_at: datetime | str, schema_version: str = "0.1") -> Node:
    if schema_version != "0.1":
        fail("UNKNOWN_VERSION", f"unsupported node version: {schema_version}")
    refs = tuple(sorted(parents))
    if len(set(refs)) != len(refs):
        fail("SCHEMA", "duplicate parent references")
    body = canonical_json(dict(schema_version=schema_version, kind=kind, payload=payload,
                               parents=[{"role": p.role, "id": p.node_id} for p in refs],
                               producer=producer, created_at=utc_timestamp(created_at)))
    return Node(content_id(body), body)


def decode_node(node_id: str, body: bytes) -> Node:
    return Node(node_id, body)
