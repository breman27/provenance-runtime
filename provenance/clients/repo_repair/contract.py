"""A provider-independent reasoning response, validated before record admission."""
import ast
from dataclasses import dataclass

from ...errors import ProvenanceError
from ...format import canonical_json, parse_json
from ...model import Parent, make_node
from ...projection import status
from .case import Evidence, TARGET, digest, candidate_snapshot
from .errors import fail

FIELDS = {"claim_statement", "evidence_aliases", "patch_content", "summary"}


@dataclass(frozen=True)
class AgentRequest:
    question: str
    contract: str
    evidence: tuple[Evidence, ...]
    history: tuple[dict, ...]
    round_index: int

    def packet(self) -> dict:
        return parse_json(canonical_json({"question": self.question, "contract": self.contract,
                                         "evidence": [{"alias": e.alias, "data": e.payload} for e in self.evidence],
                                         "history": list(self.history), "round_index": self.round_index}))


@dataclass(frozen=True)
class AgentDecision:
    claim_statement: str
    evidence_aliases: tuple[str, ...]
    patch_content: str | None
    summary: str

    def as_dict(self):
        return {"claim_statement": self.claim_statement, "evidence_aliases": list(self.evidence_aliases),
                "patch_content": self.patch_content, "summary": self.summary}


@dataclass(frozen=True)
class AgentRun:
    decision: AgentDecision
    backend: str
    live: bool
    metadata: dict


def decode_decision(data: bytes, offered: tuple[Evidence, ...]) -> AgentDecision:
    if len(data) > 1048576:
        fail("AGENT_OUTPUT_LIMIT", "proposal", "agent output exceeds 1 MiB")
    try:
        value = parse_json(data)
    except ProvenanceError as error:
        fail("AGENT_PROTOCOL", "proposal", error.problem.detail)
    if type(value) is not dict or set(value) != FIELDS:
        fail("AGENT_PROTOCOL", "proposal", "response must contain exactly the four permitted fields")
    for name in ("claim_statement", "summary"):
        if type(value[name]) is not str or not value[name].strip() or len(value[name]) > 4000:
            fail("AGENT_PROTOCOL", "proposal", f"invalid {name}")
    aliases = value["evidence_aliases"]
    allowed = {e.alias for e in offered}
    if (type(aliases) is not list or not aliases or any(type(a) is not str or a not in allowed for a in aliases)
            or len(set(aliases)) != len(aliases)):
        fail("EVIDENCE_ALIAS", "proposal", "evidence must be distinct offered aliases")
    patch = value["patch_content"]
    if patch is not None and (type(patch) is not str or len(patch.encode("utf-8")) > 8000):
        fail("PATCH_LIMIT", "proposal", "patch must be null or at most 8,000 UTF-8 bytes")
    return AgentDecision(value["claim_statement"], tuple(aliases), patch, value["summary"])


def response_schema(aliases: tuple[str, ...]) -> dict:
    return {"type": "object", "additionalProperties": False, "required": sorted(FIELDS), "properties": {
        "claim_statement": {"type": "string"}, "evidence_aliases": {"type": "array", "items": {"type": "string", "enum": list(aliases)}},
        "patch_content": {"type": ["string", "null"]}, "summary": {"type": "string"}}}


def validate_patch(content: str) -> bytes:
    if type(content) is not str:
        fail("PATCH_SHAPE", "proposal", "candidate must be text")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    try:
        data = normalized.encode("utf-8")
        if len(data) > 8000:
            fail("PATCH_LIMIT", "proposal", "candidate exceeds 8,000 bytes")
        tree = ast.parse(normalized)
    except (SyntaxError, UnicodeError, ValueError, RecursionError) as error:
        from .errors import InvestigationError
        if isinstance(error, InvestigationError):
            raise
        fail("PATCH_SHAPE", "proposal", f"candidate is not valid supported Python: {error}")
    nodes = tuple(ast.walk(tree))
    if len(nodes) > 200:
        fail("PATCH_LIMIT", "proposal", "candidate exceeds 200 syntax nodes")
    body = list(tree.body)
    docstrings = set()
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and type(body[0].value.value) is str:
        docstrings.update((id(body[0]), id(body[0].value)))
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.FunctionDef):
        fail("PATCH_SHAPE", "proposal", "candidate must define only clamp")
    function = body[0]
    if any(isinstance(node, ast.FunctionDef) and node is not function for node in nodes):
        fail('PATCH_SHAPE', 'proposal', 'nested functions and builtin shadowing are forbidden')
    args = function.args
    if (function.name != "clamp" or [a.arg for a in args.args] != ["value", "lower", "upper"]
            or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or args.defaults or args.kw_defaults
            or function.decorator_list or getattr(function, "type_params", ())):
        fail("PATCH_SHAPE", "proposal", "clamp signature or decorations differ from the allowed profile")
    annotations = [a.annotation for a in args.args] + [function.returns]
    if any(a is not None and not (isinstance(a, ast.Name) and a.id == "int") for a in annotations):
        fail("PATCH_SHAPE", "proposal", "only int annotations are allowed")
    annotation_ids = {id(a) for a in annotations if a is not None}
    if function.body and isinstance(function.body[0], ast.Expr) and isinstance(function.body[0].value, ast.Constant) and type(function.body[0].value.value) is str:
        docstrings.update((id(function.body[0]), id(function.body[0].value)))
    calls = {id(n.func) for n in nodes if isinstance(n, ast.Call)}
    allowed_types = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.If, ast.Compare,
                     ast.BoolOp, ast.UnaryOp, ast.BinOp, ast.Call, ast.Name, ast.Load, ast.Constant,
                     ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod, ast.USub, ast.UAdd, ast.Not,
                     ast.And, ast.Or, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq)
    for node in nodes:
        if id(node) in docstrings:
            continue
        if not isinstance(node, allowed_types):
            fail("PATCH_SHAPE", "proposal", f"forbidden syntax: {type(node).__name__}")
        if isinstance(node, ast.Constant) and (type(node.value) is not int or abs(node.value) > 1000000):
            fail("PATCH_SHAPE", "proposal", "candidate constants must be bounded integers")
        if isinstance(node, ast.Name):
            valid = node.id in {"value", "lower", "upper"} or id(node) in annotation_ids
            valid = valid or (id(node) in calls and node.id in {"min", "max"})
            if not valid:
                fail("PATCH_SHAPE", "proposal", "candidate references an unapproved name")
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in {"min", "max"}
                                          or not 1 <= len(node.args) <= 3 or node.keywords):
            fail("PATCH_SHAPE", "proposal", "only bounded positional min/max calls are allowed")
    return data


def admit_decision(runtime, case, baseline, request, run):
    decision = decode_decision(canonical_json(run.decision.as_dict()), request.evidence)
    offered = {e.alias: e for e in request.evidence}
    parents = []
    for alias in decision.evidence_aliases:
        evidence = offered[alias]
        report = runtime.store.validate(evidence.node_id)
        if not report.ok:
            fail("EVIDENCE_INVALID", "proposal", report.errors[0].detail)
        stored = runtime.store.get(evidence.node_id)
        if stored.kind != "Observation" or stored.payload != evidence.payload or status(runtime.store, stored.id, "execution") != "VALID":
            fail("EVIDENCE_INVALID", "proposal", "offered observation is unavailable, changed, or unusable")
        parents.append(Parent("evidence", evidence.node_id))
    patch = validate_patch(decision.patch_content) if decision.patch_content is not None else None
    proposal_status = "no_proposal" if patch is None else "unchanged" if patch == baseline.files[TARGET] else "proposed"
    payload = {"statement": decision.claim_statement, "summary": decision.summary, "proposal_status": proposal_status,
               "backend": run.backend, "live_agent": run.live, "provider_metadata": run.metadata,
               "round_index": request.round_index, "input_hash": digest(canonical_json(request.packet()))}
    claim = make_node("Claim", payload, parents, "agent:" + run.backend, runtime.clock())
    claim_id = runtime.submit(claim)
    if proposal_status != "proposed":
        return claim_id, None
    candidate = candidate_snapshot(baseline, patch)
    arguments = {"baseline_snapshot": baseline.snapshot_hash, "candidate_snapshot": candidate.snapshot_hash,
                 "target_path": TARGET, "original_file_hash": baseline.file_hashes[TARGET],
                 "patch_content": patch.decode("utf-8")}
    action = make_node("ProposedAction", {"action_type": "repo.repair.simulated",
                       "resource": "fixture:clamp:" + case.case_id, "arguments": arguments},
                       [Parent("justification", claim_id)], "agent:" + run.backend, runtime.clock())
    return claim_id, runtime.submit(action)
