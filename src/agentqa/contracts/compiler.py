from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml
from pydantic import ValidationError

from agentqa.contracts.actions import Operation
from agentqa.contracts.canonical import digest_content
from agentqa.contracts.case import (
    ActionNode,
    AndCondition,
    BranchNode,
    CaptureCondition,
    CaptureNode,
    CaseContent,
    CaseNode,
    CheckpointNode,
    ComparisonCondition,
    LoopNode,
    NotCondition,
    OrCondition,
    PostconditionClassification,
    Provenance,
)
from agentqa.contracts.errors import (
    ERROR_MESSAGES,
    AgentQAValidationError,
    ErrorCode,
    FieldError,
    field_error,
)
from agentqa.contracts.identity import TargetDescriptor
from agentqa.contracts.values import (
    CaptureValue,
    ParameterValue,
    SecretValue,
    ValueExpr,
    ValueType,
)

MAX_DOCUMENT_BYTES = 1_048_576
MAX_ANCHORS = 16
MAX_ALIASES = 32
MAX_LOOP_ITERATIONS = 1_000

OPERATION_CAPABILITIES: dict[Operation, str] = {
    Operation.UPLOAD: "file_upload",
    Operation.SWITCH_PAGE: "tab",
    Operation.SWITCH_FRAME: "frame",
    Operation.HANDLE_DIALOG: "dialog",
    Operation.EXPECT_DOWNLOAD: "download",
}

SECRET_SAFE_OPERATIONS = frozenset({Operation.FILL, Operation.TYPE})
TARGET_ONLY_COMPARATORS = frozenset({"exists", "unique"})
ANCHOR_RE = re.compile(r"&[A-Za-z0-9_-]+")
ALIAS_RE = re.compile(r"(?<![A-Za-z0-9_])\*[A-Za-z0-9_-]+")


class DuplicateKeyError(yaml.YAMLError):
    def __init__(self, path: tuple[str | int, ...], key: str) -> None:
        self.path = path
        self.key = key
        super().__init__(f"duplicate key {key!r}")


class StrictLoader(yaml.SafeLoader):
    def __init__(self, stream: Any) -> None:
        super().__init__(stream)
        self._key_path: list[str | int] = []

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        if isinstance(node, yaml.MappingNode):
            self.flatten_mapping(node)
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, (str, int, float, bool)):
                raise DuplicateKeyError(tuple(self._key_path), str(key))
            if key in mapping:
                raise DuplicateKeyError((*self._key_path, str(key)), str(key))
            saved = self._key_path
            self._key_path = [*saved, str(key)]
            try:
                mapping[key] = self.construct_object(value_node, deep=deep)
            finally:
                self._key_path = saved
        return mapping

    def construct_sequence(self, node: yaml.SequenceNode, deep: bool = False) -> list[Any]:
        result: list[Any] = []
        for index, child in enumerate(node.value):
            saved = self._key_path
            self._key_path = [*saved, index]
            try:
                result.append(self.construct_object(child, deep=deep))
            finally:
                self._key_path = saved
        return result


def parse_case_document(text: str) -> dict[str, Any]:
    raw = text.encode("utf-8")
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise AgentQAValidationError(
            [field_error((), ErrorCode.DOCUMENT_TOO_LARGE, f"Tài liệu vượt {MAX_DOCUMENT_BYTES} bytes")]
        )
    if len(ANCHOR_RE.findall(text)) > MAX_ANCHORS:
        raise AgentQAValidationError([field_error((), ErrorCode.ALIAS_LIMIT_EXCEEDED, f"Quá {MAX_ANCHORS} anchor")])
    if len(ALIAS_RE.findall(text)) > MAX_ALIASES:
        raise AgentQAValidationError([field_error((), ErrorCode.ALIAS_LIMIT_EXCEEDED, f"Quá {MAX_ALIASES} alias")])
    try:
        loaded = yaml.load(text, Loader=StrictLoader)
    except DuplicateKeyError as exc:
        raise AgentQAValidationError(
            [field_error(exc.path, ErrorCode.DUPLICATE_KEY, f"Khóa '{exc.key}' bị lặp")]
        ) from exc
    except yaml.constructor.ConstructorError as exc:
        raise AgentQAValidationError(
            [field_error((), ErrorCode.CUSTOM_TAG_REJECTED, "YAML tag tùy biến bị từ chối")]
        ) from exc
    except yaml.YAMLError as exc:
        raise AgentQAValidationError(
            [field_error((), ErrorCode.INPUT_INVALID, "YAML không parse an toàn được")]
        ) from exc
    if not isinstance(loaded, dict):
        raise AgentQAValidationError([field_error((), ErrorCode.INPUT_INVALID, "Tài liệu case phải là mapping")])
    return loaded


def _map_pydantic_error(err: dict[str, Any]) -> FieldError:
    loc = tuple(part for part in err.get("loc", ()) if part != "__root__")
    error_type = err.get("type", "")
    if "schema_version" in loc:
        code = ErrorCode.UNSUPPORTED_SCHEMA_VERSION
    elif "operation" in loc and error_type in ("enum", "literal_error"):
        code = ErrorCode.UNKNOWN_OPERATION
    elif error_type in ("union_tag_invalid", "union_tag_not_found"):
        code = ErrorCode.UNSUPPORTED_NODE
    else:
        code = ErrorCode.INPUT_INVALID
    return field_error(loc, code, f"{ERROR_MESSAGES[code]} tại {'/'.join(str(p) for p in loc)}")


def _pydantic_errors(exc: ValidationError) -> list[FieldError]:
    return [_map_pydantic_error(err) for err in exc.errors()]


@dataclass
class _CompileState:
    source_defs: dict[str, Any]
    confirmed_source_digests: frozenset[str]
    parameter_defs: dict[str, Any]
    postcondition_defs: dict[str, Any]
    captures: dict[str, ValueType] = field(default_factory=dict)
    node_ids: set[str] = field(default_factory=set)
    assertion_ids: set[str] = field(default_factory=set)
    assertion_required: dict[str, bool] = field(default_factory=dict)
    errors: list[FieldError] = field(default_factory=list)
    operations: set[Operation] = field(default_factory=set)

    def error(self, path: tuple[str | int, ...], code: ErrorCode, message: str | None = None) -> None:
        self.errors.append(field_error(path, code, message))


def _check_condition(condition: Any, path: tuple[str | int, ...], state: _CompileState) -> None:
    if isinstance(condition, ComparisonCondition):
        _check_target(condition.target, (*path, "target"), state)
        if condition.expected is not None:
            _check_value_expr(condition.expected, (*path, "expected"), state, allow_secret=False)
        return
    if isinstance(condition, CaptureCondition):
        actual = state.captures.get(condition.name)
        if actual is None:
            state.error((*path, "name"), ErrorCode.INVALID_CAPTURE, f"Capture '{condition.name}' chưa được định nghĩa")
        elif actual != ValueType.BOOLEAN:
            state.error((*path, "name"), ErrorCode.TYPE_MISMATCH, f"Capture '{condition.name}' không phải boolean")
        return
    if isinstance(condition, AndCondition):
        for index, child in enumerate(condition.conditions):
            _check_condition(child, (*path, "conditions", index), state)
        return
    if isinstance(condition, OrCondition):
        for index, child in enumerate(condition.conditions):
            _check_condition(child, (*path, "conditions", index), state)
        return
    if isinstance(condition, NotCondition):
        _check_condition(condition.condition, (*path, "condition"), state)
        return
    state.error(path, ErrorCode.UNSUPPORTED_NODE)


def _check_target(target: TargetDescriptor | None, path: tuple[str | int, ...], state: _CompileState) -> None:
    if target is None or target.entity_scope is None:
        return
    _check_value_expr(target.entity_scope.value, (*path, "entity_scope", "value"), state, allow_secret=False)


def _check_value_expr(
    expr: ValueExpr,
    path: tuple[str | int, ...],
    state: _CompileState,
    *,
    allow_secret: bool,
) -> None:
    if isinstance(expr, SecretValue):
        if not allow_secret:
            state.error(path, ErrorCode.SECRET_INTERPOLATION, "Secret không được dùng ở vị trí này")
        return
    if isinstance(expr, ParameterValue):
        parameter = state.parameter_defs.get(expr.name)
        if parameter is None:
            state.error(path, ErrorCode.UNKNOWN_REFERENCE, f"Parameter '{expr.name}' chưa được định nghĩa")
        elif parameter.type != expr.type:
            state.error(path, ErrorCode.TYPE_MISMATCH, f"Parameter '{expr.name}' khai báo {expr.type}")
        return
    if isinstance(expr, CaptureValue):
        actual = state.captures.get(expr.name)
        if actual is None:
            state.error(path, ErrorCode.INVALID_CAPTURE, f"Capture '{expr.name}' chưa được định nghĩa")
        elif actual != expr.type:
            state.error(path, ErrorCode.TYPE_MISMATCH, f"Capture '{expr.name}' khai báo {expr.type}")


def _check_sources(names: list[str], path: tuple[str | int, ...], state: _CompileState) -> None:
    for index, name in enumerate(names):
        source = state.source_defs.get(name)
        if source is None:
            state.error((*path, index), ErrorCode.UNKNOWN_REFERENCE, f"Source '{name}' chưa được định nghĩa")
            continue
        if (
            source.provenance == Provenance.INFERRED
            and source.confirmation_ref is None
            and source.source_content_digest not in state.confirmed_source_digests
        ):
            state.error(
                (*path, index),
                ErrorCode.SOURCE_UNCONFIRMED,
                f"Source '{name}' suy luận nhưng chưa được xác nhận",
            )


def _check_assertion(assertion: Any, path: tuple[str | int, ...], state: _CompileState) -> None:
    if assertion.id in state.assertion_ids:
        state.error((*path, "id"), ErrorCode.DUPLICATE_ID, f"Assertion id '{assertion.id}' bị lặp")
    state.assertion_ids.add(assertion.id)
    state.assertion_required[assertion.id] = assertion.required
    has_target = assertion.target is not None
    has_expected = assertion.expected is not None
    if assertion.comparator.value in TARGET_ONLY_COMPARATORS:
        if not has_target:
            state.error((*path, "target"), ErrorCode.EMPTY_ASSERTION, "Comparator cần target")
    elif not has_expected:
        state.error((*path, "expected"), ErrorCode.EMPTY_ASSERTION, "Comparator cần expected")
    if not has_target and not has_expected:
        state.error(path, ErrorCode.EMPTY_ASSERTION, "Assertion thiếu target và expected")
    _check_target(assertion.target, (*path, "target"), state)
    if assertion.expected is not None:
        _check_value_expr(assertion.expected, (*path, "expected"), state, allow_secret=False)
    if assertion.required and not assertion.source_refs:
        state.error((*path, "source_refs"), ErrorCode.SOURCE_UNCONFIRMED, "Assertion bắt buộc phải có nguồn")
    else:
        _check_sources(assertion.source_refs, (*path, "source_refs"), state)


def _register_node_id(node_id: str, path: tuple[str | int, ...], state: _CompileState) -> None:
    if node_id in state.node_ids:
        state.error((*path, "id"), ErrorCode.DUPLICATE_ID, f"Node id '{node_id}' bị lặp")
    state.node_ids.add(node_id)


def _walk_sequence(nodes: list[CaseNode], path: tuple[str | int, ...], state: _CompileState) -> set[str]:
    terminals: set[str] = set()
    for index, node in enumerate(nodes):
        terminals = _walk_node(node, (*path, index), state)
    return terminals


def _walk_node(node: CaseNode, path: tuple[str | int, ...], state: _CompileState) -> set[str]:
    _register_node_id(node.id, path, state)
    if isinstance(node, ActionNode):
        state.operations.add(node.operation)
        _check_target(node.target, (*path, "target"), state)
        if isinstance(node.value, SecretValue):
            if node.operation not in SECRET_SAFE_OPERATIONS:
                state.error((*path, "value"), ErrorCode.SECRET_INTERPOLATION, "Secret chỉ được fill/type")
            elif node.target is None:
                state.error((*path, "value"), ErrorCode.SECRET_INTERPOLATION, "Secret fill cần target đã xác minh")
        elif node.value is not None:
            _check_value_expr(node.value, (*path, "value"), state, allow_secret=False)
        for index, postcondition in enumerate(node.postconditions):
            if postcondition not in state.postcondition_defs:
                state.error(
                    (*path, "postconditions", index),
                    ErrorCode.UNKNOWN_REFERENCE,
                    f"Postcondition '{postcondition}' chưa định nghĩa",
                )
        return {node.id}
    if isinstance(node, CheckpointNode):
        if not node.assertions:
            state.error((*path, "assertions"), ErrorCode.EMPTY_ASSERTION, "Checkpoint không có assertion")
        for index, assertion in enumerate(node.assertions):
            _check_assertion(assertion, (*path, "assertions", index), state)
        return {node.id}
    if isinstance(node, CaptureNode):
        _check_condition(node.probe, (*path, "probe"), state)
        state.captures[node.output.name] = node.output.type
        return {node.id}
    if isinstance(node, BranchNode):
        _check_condition(node.condition, (*path, "condition"), state)
        base_captures = dict(state.captures)
        state.captures = dict(base_captures)
        then_terminals = _walk_sequence(node.then_nodes, (*path, "then_nodes"), state)
        then_captures = dict(state.captures)
        state.captures = dict(base_captures)
        else_terminals = _walk_sequence(node.else_nodes, (*path, "else_nodes"), state)
        else_captures = dict(state.captures)
        state.captures = {
            name: value
            for name, value in then_captures.items()
            if name in else_captures and else_captures[name] == value
        }
        if not node.then_nodes and not node.else_nodes:
            state.error((*path, "then_nodes"), ErrorCode.INCOMPLETE_BRANCH_PROOF, "Branch thiếu cả hai nhánh")
        return (then_terminals or {node.id}) | (else_terminals or {node.id})
    if isinstance(node, LoopNode):
        _check_condition(node.condition, (*path, "condition"), state)
        if node.max_iterations < 1 or node.max_iterations > MAX_LOOP_ITERATIONS:
            state.error(
                (*path, "max_iterations"),
                ErrorCode.LOOP_BOUND_INVALID,
                f"max_iterations phải trong 1..{MAX_LOOP_ITERATIONS}",
            )
        base_captures = dict(state.captures)
        body_terminals = _walk_sequence(node.body, (*path, "body"), state)
        state.captures = dict(base_captures)
        return body_terminals or {node.id}
    state.error(path, ErrorCode.UNSUPPORTED_NODE)
    return {node.id}


def _iter_nodes(nodes: list[CaseNode]) -> list[CaseNode]:
    collected: list[CaseNode] = []
    stack = list(nodes)
    while stack:
        node = stack.pop()
        collected.append(node)
        if isinstance(node, BranchNode):
            stack.extend(node.then_nodes)
            stack.extend(node.else_nodes)
        elif isinstance(node, LoopNode):
            stack.extend(node.body)
    return collected


def _assigned_checkpoints(case: CaseContent) -> CaseContent:
    for node in _iter_nodes(case.nodes):
        if isinstance(node, CheckpointNode):
            for assertion in node.assertions:
                if assertion.checkpoint_id is None:
                    assertion.checkpoint_id = node.id
    return case


def _semantic_errors(case: CaseContent, confirmed_source_digests: frozenset[str]) -> list[FieldError]:
    state = _CompileState(
        source_defs=case.source_defs,
        confirmed_source_digests=confirmed_source_digests,
        parameter_defs=case.parameter_defs,
        postcondition_defs=case.postcondition_defs,
    )
    terminals = _walk_sequence(case.nodes, ("nodes",), state)
    for index, name in enumerate(case.completion.required_nodes):
        if name not in state.node_ids:
            state.error(
                ("completion", "required_nodes", index),
                ErrorCode.UNKNOWN_REFERENCE,
                f"Node '{name}' chưa định nghĩa",
            )
    for name in sorted(terminals - set(case.completion.required_nodes)):
        state.error(
            ("completion", "required_nodes"),
            ErrorCode.INCOMPLETE_BRANCH_PROOF,
            f"Node kết thúc đường chạy '{name}' không có trong completion.required_nodes",
        )
    for index, name in enumerate(case.completion.required_assertions):
        if name not in state.assertion_ids:
            state.error(
                ("completion", "required_assertions", index),
                ErrorCode.UNKNOWN_REFERENCE,
                f"Assertion '{name}' chưa định nghĩa",
            )
        elif not state.assertion_required.get(name, False):
            state.error(
                ("completion", "required_assertions", index),
                ErrorCode.EMPTY_ASSERTION,
                f"Assertion '{name}' không required",
            )
    for name, postcondition in case.postcondition_defs.items():
        if postcondition.classification == PostconditionClassification.BUSINESS:
            if not postcondition.source_refs:
                state.error(
                    ("postcondition_defs", name, "source_refs"),
                    ErrorCode.SOURCE_UNCONFIRMED,
                    "Postcondition business cần source",
                )
            else:
                _check_sources(postcondition.source_refs, ("postcondition_defs", name, "source_refs"), state)
    derived = {OPERATION_CAPABILITIES[op] for op in state.operations if op in OPERATION_CAPABILITIES}
    declared = set(case.required_capabilities)
    if derived != declared:
        state.error(
            ("required_capabilities",),
            ErrorCode.CAPABILITY_MISMATCH,
            f"Capability thiếu {sorted(derived - declared)}, thừa {sorted(declared - derived)}",
        )
    return state.errors


@dataclass(frozen=True)
class CompiledCase:
    case: CaseContent
    capabilities: tuple[str, ...]
    content_digest: str


def compile_case_document(
    text: str,
    *,
    confirmed_source_digests: frozenset[str] = frozenset(),
) -> CompiledCase:
    loaded = parse_case_document(text)
    try:
        case = CaseContent.model_validate(loaded)
    except ValidationError as exc:
        raise AgentQAValidationError(_pydantic_errors(exc)) from exc
    case = _assigned_checkpoints(case)
    errors = _semantic_errors(case, confirmed_source_digests)
    if errors:
        raise AgentQAValidationError(errors)
    derived = {OPERATION_CAPABILITIES[op] for op in _collect_operations(case.nodes) if op in OPERATION_CAPABILITIES}
    return CompiledCase(
        case=case,
        capabilities=tuple(sorted(derived)),
        content_digest=digest_content(case),
    )


def _collect_operations(nodes: list[CaseNode]) -> set[Operation]:
    return {node.operation for node in _iter_nodes(nodes) if isinstance(node, ActionNode)}
