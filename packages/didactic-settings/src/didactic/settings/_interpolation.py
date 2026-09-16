r"""Interpolation grammar, evaluator and resolver registry.

The grammar is OmegaConf's:

- ``${section.field}``: absolute dotted-path reference.
- ``${.field}`` / ``${..field}``: relative reference; each leading dot
  walks one level up from the current node's parent.
- ``${a.b[0]}`` / ``${a.b.0}``: list indexing, bracketed or dotted.
- ``${a.${b}}``: nested interpolation; the inner is resolved first.
- ``"prefix_${a.b}_suffix"``: string concatenation. A standalone
  ``${a.b}`` (whole value, no surrounding text) substitutes the typed
  value; a substring substitution coerces to ``str``.
- ``${name:arg1,arg2}``: resolver call. Arguments are split on commas
  outside brackets, braces and quotes, and each argument may itself
  contain interpolations. Built-in resolvers are registered by
  :mod:`didactic.settings._resolvers`; user code adds more via
  :func:`register_resolver`, or passes a per-call mapping to
  :func:`resolve`.
- ``\${literal}``: escape; produces a literal ``${literal}``.

Cycle detection raises :class:`~didactic.settings.InterpolationError`
with the cycle path in the message. The evaluator operates on plain
dicts and lists and imports nothing from ``didactic``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Final

from didactic.settings._errors import InterpolationError
from didactic.settings._values import ConfigValue, KeyPath, dotted, leaves

ResolverFn = Callable[..., ConfigValue]
"""A resolver: called with the interpolated string arguments, returns a value.

Arguments are strings; the return value is substituted in place, typed
when the expression is the whole leaf. A resolver may call
:func:`lookup` to read other parts of the tree being interpolated.
"""

_RESOLVERS: dict[str, ResolverFn] = {}


@dataclass
class _EvalState:
    """Evaluator state for one :func:`resolve` call.

    Parameters
    ----------
    root
        The tree references resolve against.
    resolvers
        The per-call resolver overlay, consulted before the registry.
    seen
        Reference paths currently being evaluated, for cycle detection.
    stack
        Paths of the leaves whose text is being resolved, innermost last.
    """

    root: Mapping[str, ConfigValue]
    resolvers: Mapping[str, ResolverFn]
    seen: set[tuple[int | str, ...]] = field(default_factory=set[tuple[int | str, ...]])
    stack: list[tuple[str | int, ...]] = field(
        default_factory=list[tuple[str | int, ...]]
    )


_ACTIVE: ContextVar[_EvalState | None] = ContextVar(
    "didactic_settings_active_interpolation", default=None
)


def active_root() -> Mapping[str, ConfigValue] | None:
    """Return the tree currently being interpolated, or ``None``.

    Resolvers that read other parts of the tree should prefer
    :func:`lookup`, which shares cycle detection with the evaluation in
    progress; this accessor exposes the raw tree for resolvers that
    inspect its shape.
    """
    state = _ACTIVE.get()
    return None if state is None else state.root


def active_path() -> tuple[str | int, ...] | None:
    """Return the path of the leaf being resolved, or ``None``.

    Empty when a bare string (not a leaf of a tree) is being resolved.
    """
    state = _ACTIVE.get()
    if state is None or not state.stack:
        return None
    return state.stack[-1]


def lookup(path: str) -> ConfigValue:
    """Evaluate a dotted path inside the active evaluation.

    Integer segments index lists; the value found is itself interpolated
    before it is returned. Because the lookup runs inside the evaluation
    state of the enclosing :func:`resolve` call, a reference cycle that
    passes through a resolver is reported as a cycle.

    Raises
    ------
    InterpolationError
        When called outside an active :func:`resolve`, or when the path
        does not resolve.
    """
    state = _ACTIVE.get()
    if state is None:
        msg = "lookup() called outside an active resolve()"
        raise InterpolationError(msg)
    nodes = _parse("${" + path + "}") if path.strip() else ()
    if len(nodes) != 1 or not isinstance(nodes[0], _Reference):
        msg = f"lookup() expects a dotted path; got {path!r}"
        raise InterpolationError(msg)
    return _eval_reference(nodes[0], (), state, depth=0)


@contextmanager
def _activate(state: _EvalState) -> Generator[None]:
    token = _ACTIVE.set(state)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def register_resolver(name: str, fn: ResolverFn, *, replace: bool = False) -> None:
    """Register a resolver under ``name`` in the process-wide registry.

    Parameters
    ----------
    name
        Resolver name as it appears in ``${name:args}``.
    fn
        Function called with the interpolated string arguments. Its
        return value is substituted in place.
    replace
        Whether re-registration of an existing name is allowed. Off by
        default so accidental shadowing is loud.

    Raises
    ------
    ValueError
        When ``name`` is already registered and ``replace`` is false.
    """
    if name in _RESOLVERS and not replace:
        msg = f"Resolver {name!r} already registered. Pass replace=True to override."
        raise ValueError(msg)
    _RESOLVERS[name] = fn


def unregister_resolver(name: str) -> None:
    """Remove a registered resolver; a no-op when the name is absent."""
    _RESOLVERS.pop(name, None)


def list_resolvers() -> tuple[str, ...]:
    """Return the names of every registered resolver, sorted."""
    return tuple(sorted(_RESOLVERS))


# ---------------------------------------------------------------------------
# AST nodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Literal:
    """A literal string segment with no interpolation."""

    text: str


@dataclass(frozen=True)
class _Reference:
    """A reference of the form ``${path}``.

    ``up`` counts the leading dots (``${.x}`` is ``up=1``, ``${..x}`` is
    ``up=2``, ``${x}`` is ``up=0``). Each element of ``parts`` is a string
    (a dict key), an integer (a list index) or a node tuple (a nested
    expression evaluated to a segment first).
    """

    up: int
    parts: tuple[_PathSegment, ...]


@dataclass(frozen=True)
class _ResolverCall:
    """A resolver call of the form ``${name:arg1,arg2}``.

    ``args`` holds one node tuple per argument, since arguments may
    themselves contain interpolations.
    """

    name: str
    args: tuple[tuple[_Node, ...], ...]


type _PathSegment = str | int | tuple[_Node, ...]
"""One element of an interpolation path."""

type _Node = _Literal | _Reference | _ResolverCall
"""One element of a parsed expression."""


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


_OPENERS: Final = {"[": "]", "{": "}"}


@dataclass
class _Parser:
    """Recursive-descent parser for interpolation strings.

    Maintains a single ``pos`` cursor into ``text``. Methods that parse a
    construct return its AST and advance the cursor.
    """

    text: str
    pos: int = 0

    def parse(self) -> tuple[_Node, ...]:
        """Parse the whole text into a node tuple."""
        return self._parse_until(end_chars=())

    def _parse_until(self, *, end_chars: tuple[str, ...]) -> tuple[_Node, ...]:
        nodes: list[_Node] = []
        buf: list[str] = []

        def flush_literal() -> None:
            if buf:
                nodes.append(_Literal("".join(buf)))
                buf.clear()

        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch in end_chars:
                break
            if ch == "\\" and self.pos + 1 < len(self.text):
                nxt = self.text[self.pos + 1]
                if nxt == "$":
                    buf.append("$")
                    self.pos += 2
                    continue
                if nxt == "\\":
                    buf.append("\\")
                    self.pos += 2
                    continue
                buf.append(ch)
                self.pos += 1
                continue
            if ch == "$" and self._peek(1) == "{":
                flush_literal()
                nodes.append(self._parse_interp())
                continue
            buf.append(ch)
            self.pos += 1

        flush_literal()
        return tuple(nodes)

    def _peek(self, offset: int) -> str:
        idx = self.pos + offset
        if 0 <= idx < len(self.text):
            return self.text[idx]
        return ""

    def _parse_interp(self) -> _Node:
        """Parse a ``${...}`` expression starting at ``self.pos``."""
        self.pos += 2  # consume "${"

        up = 0
        while self.pos < len(self.text) and self.text[self.pos] == ".":
            up += 1
            self.pos += 1

        parts: list[_PathSegment] = []
        head, head_terminator = self._parse_path_head()
        if head != "" or head_terminator == ":":
            parts.append(head)
        while head_terminator == ".":
            seg, head_terminator = self._parse_path_head()
            if seg == "":
                msg = f"Empty path segment in interpolation at pos {self.pos}"
                raise InterpolationError(msg)
            parts.append(seg)

        if head_terminator == ":":
            if up != 0:
                msg = "Resolver call cannot have leading dots"
                raise InterpolationError(msg)
            if not parts or not all(isinstance(p, str) and p != "" for p in parts):
                msg = "Resolver name must be a static dotted identifier"
                raise InterpolationError(msg)
            name = ".".join(p for p in parts if isinstance(p, str))
            args = self._parse_resolver_args()
            self._expect("}")
            return _ResolverCall(name=name, args=args)

        if head_terminator == "[":
            head_terminator = self._parse_indices(parts)

        if head_terminator != "}":
            msg = f"Unexpected character {head_terminator!r} in interpolation"
            raise InterpolationError(msg)
        self.pos += 1  # consume "}"
        return _Reference(up=up, parts=tuple(parts))

    def _parse_indices(self, parts: list[_PathSegment]) -> str:
        """Parse one or more ``[i]`` indices (each optionally followed by ``.seg``).

        Appends the segments to ``parts`` and returns the terminator that
        follows them: ``"}"`` at the end of the expression, or whatever
        character ended a trailing dotted segment.
        """
        terminator = "["
        while terminator == "[":
            self.pos += 1  # consume "["
            idx_text = self._read_until("]")
            self._expect("]")
            try:
                parts.append(int(idx_text))
            except ValueError as exc:
                msg = f"Bracketed index must be an integer: [{idx_text!r}]"
                raise InterpolationError(msg) from exc
            if self._peek(0) == ".":
                self.pos += 1
                seg, terminator = self._parse_path_head()
                if seg == "":
                    msg = "Empty path segment after ']'"
                    raise InterpolationError(msg)
                parts.append(seg)
            elif self._peek(0) == "[":
                terminator = "["
            else:
                terminator = "}"
        return terminator

    def _parse_path_head(self) -> tuple[_PathSegment, str]:
        """Read one path segment, returning ``(segment, terminator)``.

        The terminator is ``"."`` (more dotted path follows), ``"["``
        (bracketed index follows), ``":"`` (resolver arguments follow),
        ``"}"`` (end of expression) or ``""`` (end of text). A segment
        containing a nested ``${...}`` is returned as a node tuple.
        """
        buf: list[str] = []
        nested: list[_Node] | None = None
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch in (".", "[", ":", "}"):
                terminator = ch
                if ch == ".":
                    self.pos += 1
                break
            if ch == "$" and self._peek(1) == "{":
                if nested is None:
                    nested = []
                    if buf:
                        nested.append(_Literal("".join(buf)))
                        buf.clear()
                nested.append(self._parse_interp())
                continue
            buf.append(ch)
            self.pos += 1
        else:
            terminator = ""

        if nested is not None:
            if buf:
                nested.append(_Literal("".join(buf)))
            seg: _PathSegment = tuple(nested)
        else:
            seg = "".join(buf)
            if seg.lstrip("-").isdigit():
                seg = int(seg)
        return seg, terminator

    def _parse_resolver_args(self) -> tuple[tuple[_Node, ...], ...]:
        """Parse the argument list of a resolver call after the ``:``.

        Arguments are separated by commas at bracket depth zero and
        outside quotes, so ``[1, 2]``, ``{"a": 1}`` and ``"x,y"`` each
        pass as one argument. Surrounding whitespace is dropped, and an
        argument that is entirely one quoted string loses its quotes.
        """
        self.pos += 1  # consume ":"
        args: list[tuple[_Node, ...]] = []
        current: list[_Node] = []
        buf: list[str] = []
        closers: list[str] = []
        quote: str | None = None

        def flush_literal() -> None:
            if buf:
                current.append(_Literal("".join(buf)))
                buf.clear()

        def finish_argument() -> None:
            flush_literal()
            args.append(_trim_argument(tuple(current)))
            current.clear()

        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch == "\\" and self.pos + 1 < len(self.text):
                buf.append(self.text[self.pos + 1])
                self.pos += 2
                continue
            if ch == "$" and self._peek(1) == "{":
                flush_literal()
                current.append(self._parse_interp())
                continue
            if quote is not None:
                if ch == quote:
                    quote = None
            elif ch in ("'", '"'):
                quote = ch
            elif ch in _OPENERS:
                closers.append(_OPENERS[ch])
            elif closers:
                if ch == closers[-1]:
                    closers.pop()
            elif ch == "}":
                finish_argument()
                return tuple(args)
            elif ch == ",":
                finish_argument()
                self.pos += 1
                continue
            buf.append(ch)
            self.pos += 1
        msg = "Unterminated resolver call (missing '}')"
        raise InterpolationError(msg)

    def _read_until(self, terminator: str) -> str:
        """Read literal text up to ``terminator``, which is left unread."""
        start = self.pos
        while self.pos < len(self.text):
            if self.text[self.pos] == terminator:
                return self.text[start : self.pos]
            self.pos += 1
        msg = f"Unterminated bracket: expected {terminator!r}"
        raise InterpolationError(msg)

    def _expect(self, ch: str) -> None:
        if self.pos >= len(self.text) or self.text[self.pos] != ch:
            msg = (
                f"Expected {ch!r} at pos {self.pos}; "
                f"got {self.text[self.pos : self.pos + 1]!r}"
            )
            raise InterpolationError(msg)
        self.pos += 1


def _trim_argument(nodes: tuple[_Node, ...]) -> tuple[_Node, ...]:
    """Drop surrounding whitespace and, for a lone quoted literal, its quotes."""
    if not nodes:
        return nodes
    trimmed = list(nodes)
    first = trimmed[0]
    if isinstance(first, _Literal):
        trimmed[0] = _Literal(first.text.lstrip())
    last = trimmed[-1]
    if isinstance(last, _Literal):
        text = last.text.rstrip()
        if (
            len(trimmed) == 1
            and len(text) >= 2
            and text[0] == text[-1]
            and text[0] in "\"'"
        ):
            text = text[1:-1]
        trimmed[-1] = _Literal(text)
    return tuple(node for node in trimmed if node != _Literal(""))


def _parse(text: str) -> tuple[_Node, ...]:
    return _Parser(text).parse()


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


_MAX_DEPTH: Final = 64


def resolve(
    node: ConfigValue,
    *,
    root: Mapping[str, ConfigValue],
    here: tuple[str | int, ...] = (),
    resolvers: Mapping[str, ResolverFn] | None = None,
) -> ConfigValue:
    """Resolve every interpolation in ``node``, returning a new value.

    Strings are parsed and evaluated; dicts and lists are descended with
    ``here`` extended by the key or index. A string that is exactly one
    expression substitutes the typed value (resolving ``"${a.b}"`` where
    ``a.b`` is an int gives an int); a substring substitution coerces to
    ``str``.

    Parameters
    ----------
    node
        The value to resolve.
    root
        The tree references resolve against.
    here
        Path of ``node`` within ``root``, for relative references.
    resolvers
        Resolvers consulted before the process-wide registry, for this
        call only.

    Raises
    ------
    InterpolationError
        For an unresolved reference, an unknown resolver, a resolver that
        raised, a cycle or a syntax error. The error's ``path`` names the
        leaf whose text was being resolved.
    """
    state = _EvalState(root=root, resolvers=resolvers or {})
    with _activate(state):
        return _resolve_value(node, here, state)


def resolve_traced(
    document: Mapping[str, ConfigValue],
    *,
    root: Mapping[str, ConfigValue] | None = None,
    resolvers: Mapping[str, ResolverFn] | None = None,
) -> tuple[dict[str, ConfigValue], dict[KeyPath, str]]:
    """Resolve a whole document and report which leaves held expressions.

    Parameters
    ----------
    document
        The document whose leaves are resolved.
    root
        The tree references resolve against; ``document`` itself when
        omitted. The composition engine passes the document backed by the
        schema's defaults, so a reference to a field no layer set reads
        the model's default.
    resolvers
        Resolvers consulted before the process-wide registry, for this
        call only.

    Returns
    -------
    tuple
        The resolved document, and ``{path: text}`` for every dict-keyed
        leaf whose source text contained ``${``: the string itself for a
        string leaf, the JSON rendering of the list as written for a list
        leaf any of whose elements contained ``${``.
    """
    expressions: dict[KeyPath, str] = {}
    for path, value in leaves(document):
        if isinstance(value, str):
            if mentions_expression(value):
                expressions[path] = value
        elif isinstance(value, list) and mentions_expression(value):
            expressions[path] = json.dumps(value)
    state = _EvalState(
        root=document if root is None else root, resolvers=resolvers or {}
    )
    with _activate(state):
        resolved = {
            key: _resolve_value(value, (key,), state) for key, value in document.items()
        }
    return resolved, expressions


def mentions_expression(value: ConfigValue) -> bool:
    """Whether a value holds an unescaped ``${...}`` anywhere inside it.

    Text the parser refuses counts as an expression, so the resolution
    that follows reports the syntax error with the leaf's path.
    """
    if isinstance(value, str):
        if "${" not in value:
            return False
        try:
            nodes = _parse(value)
        except InterpolationError:
            return True
        return any(not isinstance(node, _Literal) for node in nodes)
    if isinstance(value, list):
        return any(mentions_expression(item) for item in value)
    if isinstance(value, Mapping):
        return any(mentions_expression(item) for item in value.values())
    return False


def is_whole_expression(text: str) -> bool:
    """Whether the text is exactly one ``${...}`` expression and nothing else.

    Such a leaf substitutes the typed value the expression evaluates to,
    so a list or mapping may arrive at a slot that way; text with
    surrounding literal characters always resolves to a string.
    """
    if "${" not in text:
        return False
    try:
        nodes = _parse(text)
    except InterpolationError:
        return False
    return len(nodes) == 1 and not isinstance(nodes[0], _Literal)


def _resolve_value(
    node: ConfigValue,
    here: tuple[str | int, ...],
    state: _EvalState,
) -> ConfigValue:
    if isinstance(node, str):
        return _resolve_string(node, here, state)
    if isinstance(node, list):
        return [_resolve_value(item, (*here, i), state) for i, item in enumerate(node)]
    if isinstance(node, Mapping):
        return {
            key: _resolve_value(value, (*here, key), state)
            for key, value in node.items()
        }
    return node


def _resolve_string(
    text: str, here: tuple[str | int, ...], state: _EvalState
) -> ConfigValue:
    if "${" not in text and "\\" not in text:
        return text
    state.stack.append(here)
    try:
        nodes = _parse(text)
        if len(nodes) == 1 and not isinstance(nodes[0], _Literal):
            return _eval_node(nodes[0], here, state, depth=0)
        parts: list[str] = []
        for node in nodes:
            value = _eval_node(node, here, state, depth=0)
            parts.append(value if isinstance(value, str) else _to_str(value))
        return "".join(parts)
    except InterpolationError as exc:
        if exc.path is None:
            exc.path = here
            if here:
                exc.args = (f"{exc.args[0]}; at config key {_format_path(here)!r}",)
        raise
    finally:
        state.stack.pop()


def _eval_node(
    node: _Node, here: tuple[str | int, ...], state: _EvalState, *, depth: int
) -> ConfigValue:
    if depth > _MAX_DEPTH:
        msg = f"Interpolation nesting exceeded {_MAX_DEPTH} levels"
        raise InterpolationError(msg)
    if isinstance(node, _Literal):
        return node.text
    if isinstance(node, _Reference):
        return _eval_reference(node, here, state, depth=depth)
    return _eval_resolver_call(node, here, state, depth=depth)


def _eval_reference(
    ref: _Reference,
    here: tuple[str | int, ...],
    state: _EvalState,
    *,
    depth: int,
) -> ConfigValue:
    if ref.up > len(here):
        msg = (
            f"Relative reference {'.' * ref.up}... walks above the "
            f"root (current path: {_format_path(here)})"
        )
        raise InterpolationError(msg)
    base_path = here[: len(here) - ref.up] if ref.up > 0 else ()
    resolved_parts: list[str | int] = list(base_path)
    for part in ref.parts:
        resolved_parts.append(_resolve_path_segment(part, here, state, depth=depth + 1))

    cycle_key: tuple[int | str, ...] = (id(state.root), *resolved_parts)
    if cycle_key in state.seen:
        msg = f"Interpolation cycle detected at {_format_path(resolved_parts)}"
        raise InterpolationError(msg)
    state.seen.add(cycle_key)
    try:
        value = _walk(state.root, resolved_parts)
        if isinstance(value, str | Mapping | list):
            return _resolve_value(value, tuple(resolved_parts), state)
        return value
    finally:
        state.seen.discard(cycle_key)


def _eval_resolver_call(
    call: _ResolverCall,
    here: tuple[str | int, ...],
    state: _EvalState,
    *,
    depth: int,
) -> ConfigValue:
    fn = state.resolvers.get(call.name) or _RESOLVERS.get(call.name)
    if fn is None:
        registered = ", ".join(sorted({*state.resolvers, *_RESOLVERS}))
        msg = f"Unknown resolver {call.name!r}; registered: {registered}"
        raise InterpolationError(msg)
    resolved_args: list[str] = []
    for arg_nodes in call.args:
        rendered: list[str] = []
        for sub in arg_nodes:
            value = _eval_node(sub, here, state, depth=depth + 1)
            rendered.append(value if isinstance(value, str) else _to_str(value))
        resolved_args.append("".join(rendered))

    try:
        return fn(*resolved_args)
    except InterpolationError:
        raise
    except Exception as exc:
        msg = f"Resolver {call.name!r} raised {type(exc).__name__}: {exc}"
        raise InterpolationError(msg) from exc


def _resolve_path_segment(
    seg: _PathSegment,
    here: tuple[str | int, ...],
    state: _EvalState,
    *,
    depth: int,
) -> str | int:
    if isinstance(seg, str | int):
        return seg
    rendered: list[str] = []
    for sub in seg:
        value = _eval_node(sub, here, state, depth=depth)
        rendered.append(value if isinstance(value, str) else _to_str(value))
    joined = "".join(rendered)
    if joined.lstrip("-").isdigit():
        return int(joined)
    return joined


class MissingReferenceError(InterpolationError):
    """A reference names a key or index the tree does not hold.

    Distinguished from the other interpolation failures so ``oc.select``
    can fall back to its default for an absent path while a cycle or a
    malformed expression still propagates.
    """


def _walk(
    root: ConfigValue, path: list[str | int] | tuple[str | int, ...]
) -> ConfigValue:
    cur: ConfigValue = root
    for i, part in enumerate(path):
        if isinstance(cur, Mapping):
            if not isinstance(part, str):
                msg = f"Cannot index dict at {_format_path(path[: i + 1])} with integer"
                raise InterpolationError(msg)
            if part not in cur:
                msg = f"Reference {_format_path(path[: i + 1])} unresolved"
                raise MissingReferenceError(msg)
            cur = cur[part]
        elif isinstance(cur, list):
            if not isinstance(part, int):
                msg = (
                    f"Cannot index list at "
                    f"{_format_path(path[: i + 1])} with non-integer"
                )
                raise InterpolationError(msg)
            if part < 0 or part >= len(cur):
                msg = (
                    f"List index out of range at "
                    f"{_format_path(path[: i + 1])} (len={len(cur)})"
                )
                raise MissingReferenceError(msg)
            cur = cur[part]
        else:
            msg = f"Cannot descend into scalar at {_format_path(path[:i])}"
            raise MissingReferenceError(msg)
    return cur


def _format_path(path: list[str | int] | tuple[str | int, ...]) -> str:
    if not path:
        return "<root>"
    return dotted(tuple(f"[{p}]" if isinstance(p, int) else p for p in path))


def _to_str(value: ConfigValue) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


__all__ = [
    "MissingReferenceError",
    "ResolverFn",
    "active_path",
    "active_root",
    "is_whole_expression",
    "list_resolvers",
    "lookup",
    "mentions_expression",
    "register_resolver",
    "resolve",
    "resolve_traced",
    "unregister_resolver",
]
