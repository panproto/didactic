"""Axiom enforcement: parse axiom strings into predicates run at construction.

Each ``__axioms__`` entry is parsed into a panproto ``Expr`` AST via
``panproto.parse_expr`` (after a small Python-friendly preprocessing
pass), then evaluated against a Model instance's field values during
construction. Failures raise
[didactic.api.ValidationError][didactic.api.ValidationError] with the axiom's
message.

Surface syntax
--------------

The accepted surface syntax is panproto's Haskell-flavoured expression
language augmented with Python-friendly synonyms:

- ``!=``  is rewritten to ``/=`` (panproto's spelling of "not equal").
- ``and`` / ``or`` keywords are rewritten to ``&&`` / ``||``.
- ``null`` / ``None`` are rewritten to panproto's ``Nothing`` literal,
  which evaluates to Python ``None``. Optional fields holding ``None``
  compare equal to ``Nothing``.
- ``X is null``      -> ``X == Nothing``.
- ``X is not null``  -> ``X /= Nothing``.

The preprocessor respects string literals: substrings inside ``"..."``
are not touched.

The evaluator walks the panproto Expr ``to_dict()`` form. Supported
shapes: ``Var``, ``Lit`` (``Int``/``Float``/``Str``/``Bool``/``Char``
and the ``"Null"`` sentinel), ``Builtin`` (every comparison and boolean
operator, plus arithmetic and ``Len``/``Head``/``Tail``/``Abs``/
``Concat``/``Map``/``Filter``/``Edge``), ``App`` (function application:
``Just X`` unwraps to ``X``, ``Nothing`` -> ``None``; ``min``/``max``/
``abs``/``and``/``or``/``sum``/``all``/``any``/``elem``/``len`` resolve
to their Python equivalents), ``Field`` (``a.b`` -> ``getattr``),
``List`` literal, ``Match`` (``if/then/else`` and pattern matching on
``Bool`` / ``Wildcard`` / literal arms), ``Lam`` (lambda), and ``Let``.

See Also
--------
didactic.axioms._axioms : the Axiom record type and ``__axioms__`` collection.
panproto.parse_expr : the underlying parser.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from didactic.axioms._axioms import Axiom
    from didactic.types._typing import FieldValue, JsonValue

# A panproto Expr ``to_dict()`` AST node is one of any JsonValue-shaped
# payload — at the leaves of dispatch we narrow with ``match`` /
# ``isinstance``. Using ``JsonValue`` (rather than the narrower
# "single-key dict envelope" shape) lets list-positional accesses like
# ``args[0]`` inside ``Builtin`` typecheck without a per-element
# ``isinstance`` chain.
type ExprNode = JsonValue
# The evaluator returns a Python value whose runtime type depends on
# the expression: a literal evaluates to a scalar, a variable lookup
# returns whatever ``env`` holds, an arithmetic op returns the result
# of Python's operator protocol over those leaves. The union is
# constructed from the documented ``FieldValue`` set (everything that
# can sit in an environment binding); callers narrow per use site
# (e.g. the predicate wrapper ``_predicate`` casts the result to
# ``bool``).
type EvalResult = FieldValue


# Word-boundary patterns for the Pythonic-syntax preprocessor. Each
# rule is a (pattern, replacement) pair applied to the substring of
# the axiom source that lies *outside* string literals; ``preprocess``
# walks the source character-by-character so the rules never fire
# inside ``"..."``.
_PYTHON_SUBSTITUTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # ``X is null`` / ``X is not null`` rewrite. Match minimally so
    # ``is`` between unrelated identifiers (rare in axiom syntax) is
    # untouched. Rewrite to panproto's Haskell spellings.
    (re.compile(r"\bis\s+not\s+null\b"), "/= Nothing"),
    (re.compile(r"\bis\s+null\b"), "== Nothing"),
    # ``!=`` -> ``/=`` (panproto's "not equal").
    (re.compile(r"!="), "/="),
    # ``null`` / ``None`` literal -> panproto's ``Nothing``.
    (re.compile(r"\bnull\b"), "Nothing"),
    (re.compile(r"\bNone\b"), "Nothing"),
    # ``and`` / ``or`` keywords -> ``&&`` / ``||``.
    (re.compile(r"\band\b"), "&&"),
    (re.compile(r"\bor\b"), "||"),
)


def preprocess_axiom_source(src: str) -> str:
    r"""Translate Python-friendly axiom syntax to panproto's spellings.

    Walks ``src`` character by character so the rules never fire inside
    string literals. Supports both ``"..."`` and ``'...'`` quoting and
    the standard ``\`` escape inside them.

    See module docstring for the rule list.
    """
    out: list[str] = []
    i = 0
    chunk_start = 0
    while i < len(src):
        ch = src[i]
        if ch in ('"', "'"):
            # flush the outside chunk (rules apply), then walk the string
            # contents through unchanged.
            outside = src[chunk_start:i]
            for pattern, repl in _PYTHON_SUBSTITUTIONS:
                outside = pattern.sub(repl, outside)
            out.append(outside)
            quote = ch
            string_start = i
            i += 1
            while i < len(src):
                if src[i] == "\\" and i + 1 < len(src):
                    i += 2
                    continue
                if src[i] == quote:
                    i += 1
                    break
                i += 1
            out.append(src[string_start:i])
            chunk_start = i
            continue
        i += 1
    tail = src[chunk_start:]
    for pattern, repl in _PYTHON_SUBSTITUTIONS:
        tail = pattern.sub(repl, tail)
    out.append(tail)
    return "".join(out)


def parse_axiom_predicate(axiom: Axiom) -> Callable[[dict[str, FieldValue]], bool]:
    """Parse an axiom expression into a callable predicate.

    Parameters
    ----------
    axiom
        An [Axiom][didactic.api.Axiom] instance whose ``expr`` is the
        surface syntax accepted by ``panproto.parse_expr`` plus the
        Python-friendly synonyms documented in the module header.

    Returns
    -------
    Callable[[dict[str, FieldValue]], bool]
        A predicate that takes a ``{field_name: value}`` environment
        and returns whether the axiom holds.

    Raises
    ------
    panproto.ExprError
        If the axiom cannot be parsed.

    Notes
    -----
    The parser is invoked once per ``Axiom``; cache the result if you
    plan to evaluate the same axiom many times.
    """
    import panproto  # noqa: PLC0415

    rewritten = preprocess_axiom_source(axiom.expr)
    expr = panproto.parse_expr(rewritten)
    # ``Expr.to_dict()`` returns ``dict[str, object]`` (the panproto
    # binding doesn't declare a tighter type because the leaf values
    # are dynamic). Cast to the ``JsonValue`` shape ``_evaluate``
    # expects; the runtime contract guarantees JSON-shaped leaves.
    ast = cast("JsonValue", expr.to_dict())

    def _predicate(env: dict[str, FieldValue]) -> bool:
        return bool(_evaluate(ast, env))

    return _predicate


def _evaluate(node: ExprNode, env: dict[str, FieldValue]) -> EvalResult:
    """Walk a panproto Expr ``to_dict`` AST and evaluate against ``env``.

    Handles the full panproto Expr surface that shows up in axiom
    expressions: variables, literals (including the ``"Null"``
    sentinel for ``Nothing``), comparisons, boolean connectives,
    arithmetic, ``Just``/``Nothing`` constructors, function
    application (``App``), field access, list literals,
    ``if/then/else`` (``Match``), pattern matching, lambdas, and
    ``let`` bindings. Unrecognised shapes raise ``NotImplementedError``.

    Pattern-matched on the panproto Expr shape: each variant is
    a single-key dict whose value has a known structure. The match
    statements narrow the dynamic ``ExprNode`` shape into the typed
    sub-shapes the helpers consume.
    """
    # Tuples flow through panproto's bindings as plain Python tuples
    # (e.g. ``Builtin: (op, args)``); pattern-match on either form so
    # the dispatcher tolerates both.
    match node:
        case {"Var": str(name)}:
            if name == "Nothing":
                return None
            if name in env:
                return env[name]
            msg = f"axiom references unbound variable {name!r}"
            raise NameError(msg)
        case {"Lit": "Null"}:
            return None
        case {"Lit": dict(lit)}:
            return _evaluate_literal(lit)
        case {"Builtin": (str(op), args)} | {"Builtin": [str(op), args]}:
            return _evaluate_builtin(op, list(cast("Sequence[ExprNode]", args)), env)
        case {"App": (func, arg)} | {"App": [func, arg]}:
            return _evaluate_app(func, arg, env)
        case {"Field": (target, str(field_name))} | {
            "Field": [target, str(field_name)]
        }:
            target_value = _evaluate(target, env)
            try:
                return cast("EvalResult", getattr(target_value, field_name))
            except AttributeError as exc:
                msg = (
                    f"axiom field access {field_name!r} failed on "
                    f"{type(target_value).__name__}"
                )
                raise NameError(msg) from exc
        case {"List": list(items)}:
            return cast("EvalResult", [_evaluate(item, env) for item in items])
        case {"Match": dict(payload)}:
            return _evaluate_match(payload, env)
        case {"Let": dict(payload)}:
            return _evaluate_let(payload, env)
        case {"Lam": (str(_), _)} | {"Lam": [str(_), _]}:
            # Lambdas only show up as the head of an App; ``_evaluate_app``
            # binds and recurses. A bare lambda outside an App position
            # has no defined value at axiom time.
            msg = "bare lambda outside an application is not supported in axioms"
            raise NotImplementedError(msg)
        case _:
            msg = f"unsupported Expr node shape: {node!r}"
            raise NotImplementedError(msg)


def _evaluate_literal(lit: ExprNode) -> EvalResult:
    """Evaluate a panproto literal node."""
    match lit:
        case {"Int": int(v) | str(v)}:
            return int(v)
        case {"Float": float(v) | int(v) | str(v)}:
            return float(v)
        case {"Str": str(v)}:
            return v
        case {"Bool": bool(v)}:
            return v
        case {"Char": str(v)}:
            return v
        case _:
            msg = f"unsupported Literal: {lit!r}"
            raise NotImplementedError(msg)


# Single-argument builtins reachable as ``App`` heads (panproto parses
# ``min a b`` as ``App(App(Var('min'), a), b)`` rather than
# ``Builtin('Min', [a, b])``). Each entry is a callable taking the
# already-evaluated argument list.
_APP_BUILTINS_BY_NAME: dict[str, Callable[[list[FieldValue]], FieldValue]] = {
    "Just": lambda a: a[0],
    "min": lambda a: min(a[0], a[1]),  # type: ignore[type-var]
    "max": lambda a: max(a[0], a[1]),  # type: ignore[type-var]
    "abs": lambda a: abs(a[0]),  # type: ignore[arg-type]
    "len": lambda a: len(a[0]),  # type: ignore[arg-type]
    "and": lambda a: all(bool(x) for x in cast("list[object]", a[0])),
    "or": lambda a: any(bool(x) for x in cast("list[object]", a[0])),
    "all": lambda a: all(bool(x) for x in cast("list[object]", a[0])),
    "any": lambda a: any(bool(x) for x in cast("list[object]", a[0])),
    "sum": lambda a: sum(cast("list[float]", a[0])),
    "elem": lambda a: a[0] in cast("list[object]", a[1]),
    "fst": lambda a: a[0][0],  # type: ignore[index]
    "snd": lambda a: a[0][1],  # type: ignore[index]
    "id": lambda a: a[0],
}


def _flatten_app(func: ExprNode, arg: ExprNode) -> tuple[ExprNode, list[ExprNode]]:
    """Unfold a curried ``App(App(..., a1), aN)`` into ``(head, [a1, ..., aN])``."""
    head: ExprNode = func
    rev_args: list[ExprNode] = [arg]
    while True:
        match head:
            case {"App": (next_head, next_arg)} | {"App": [next_head, next_arg]}:
                rev_args.append(next_arg)
                head = next_head
            case _:
                break
    return head, list(reversed(rev_args))


def _evaluate_app(
    func: ExprNode, arg: ExprNode, env: dict[str, FieldValue]
) -> EvalResult:
    """Evaluate a function application.

    ``Just X`` unwraps to ``X``; ``Nothing`` (as a head) yields
    ``None`` (with the argument ignored, matching panproto's nullary
    constructor convention). Bare ``Var``-headed apps look the head up
    in the per-axiom builtin table; ``Lam``-headed apps bind and
    recurse on the body.
    """
    head, args = _flatten_app(func, arg)
    match head:
        case {"Var": "Nothing"} | {"Lit": "Null"}:
            return None
        case {"Var": str(name)} if name in _APP_BUILTINS_BY_NAME:
            evaluated = [_evaluate(a, env) for a in args]
            return _APP_BUILTINS_BY_NAME[name](evaluated)
        case {"Var": "not"}:
            return not bool(_evaluate(args[0], env))
        case {"Lam": (str(param), body)} | {"Lam": [str(param), body]}:
            new_env = dict(env)
            new_env[param] = _evaluate(args[0], env)
            result = _evaluate(body, new_env)
            for extra in args[1:]:
                result = _evaluate_app(
                    cast("ExprNode", {"Lit": {"Int": 0}}),  # placeholder unused
                    extra,
                    {**new_env, "__result__": result},
                )
            return result
        case {"Var": str(name)}:
            msg = f"axiom evaluator does not yet implement function {name!r}"
            raise NotImplementedError(msg)
        case _:
            msg = f"axiom evaluator does not support App-head shape {head!r}"
            raise NotImplementedError(msg)


def _evaluate_match(payload: ExprNode, env: dict[str, FieldValue]) -> EvalResult:
    """Evaluate an ``if/then/else`` or pattern-match expression.

    panproto compiles ``if a then b else c`` to a ``Match`` over
    ``a`` with arms ``[(Lit Bool True, b), (Wildcard, c)]``. The
    general form supports literal-pattern arms and a ``"Wildcard"``
    fallback.
    """
    if not isinstance(payload, dict):
        msg = f"Match payload must be a dict, got {type(payload).__name__}"
        raise NotImplementedError(msg)
    scrutinee = payload.get("scrutinee")
    arms = payload.get("arms")
    if scrutinee is None or not isinstance(arms, list):
        msg = f"Match payload missing scrutinee/arms: {payload!r}"
        raise NotImplementedError(msg)
    value = _evaluate(cast("ExprNode", scrutinee), env)
    for arm in arms:
        if not isinstance(arm, (tuple, list)) or len(arm) != 2:
            msg = f"Match arm must be (pattern, body), got {arm!r}"
            raise NotImplementedError(msg)
        pattern, body = arm[0], arm[1]
        if pattern == "Wildcard":
            return _evaluate(cast("ExprNode", body), env)
        if isinstance(pattern, dict):
            pat_value = _evaluate(cast("ExprNode", pattern), env)
            if pat_value == value:
                return _evaluate(cast("ExprNode", body), env)
            continue
        msg = f"axiom evaluator does not support Match pattern {pattern!r}"
        raise NotImplementedError(msg)
    msg = f"Match has no arm covering scrutinee value {value!r}"
    raise NameError(msg)


def _evaluate_let(payload: ExprNode, env: dict[str, FieldValue]) -> EvalResult:
    """Evaluate a ``let name = value in body`` expression."""
    if not isinstance(payload, dict):
        msg = f"Let payload must be a dict, got {type(payload).__name__}"
        raise NotImplementedError(msg)
    name = payload.get("name")
    value_node = payload.get("value")
    body_node = payload.get("body")
    if not isinstance(name, str) or value_node is None or body_node is None:
        msg = f"Let payload missing name/value/body: {payload!r}"
        raise NotImplementedError(msg)
    new_env = dict(env)
    new_env[name] = _evaluate(cast("ExprNode", value_node), env)
    return _evaluate(cast("ExprNode", body_node), new_env)


def _evaluate_builtin(
    op: str,
    args: Sequence[ExprNode],
    env: dict[str, FieldValue],
) -> EvalResult:
    """Evaluate a panproto builtin operator.

    All comparison and arithmetic operators rely on Python's
    duck-typed operator protocols; the values come from
    ``_evaluate``'s ``EvalResult`` (an alias for ``object``) and the
    runtime contract is that an axiom expression's leaf values are
    comparable with the relevant operators. ``# type: ignore`` markers
    sit at each operator site because pyright cannot prove that
    arbitrary ``object`` values support ``<``/``+``/etc.
    """
    # comparison and equality (panproto uses Gte/Lte/Neq variants)
    if op == "Eq":
        a, b = (_evaluate(args[0], env), _evaluate(args[1], env))
        return a == b
    if op in ("Ne", "Neq"):
        return _evaluate(args[0], env) != _evaluate(args[1], env)
    if op == "Lt":
        return _evaluate(args[0], env) < _evaluate(args[1], env)  # type: ignore[operator]
    if op in ("Le", "Lte"):
        return _evaluate(args[0], env) <= _evaluate(args[1], env)  # type: ignore[operator]
    if op == "Gt":
        return _evaluate(args[0], env) > _evaluate(args[1], env)  # type: ignore[operator]
    if op in ("Ge", "Gte"):
        return _evaluate(args[0], env) >= _evaluate(args[1], env)  # type: ignore[operator]

    # boolean connectives
    if op == "And":
        return all(bool(_evaluate(a, env)) for a in args)
    if op == "Or":
        return any(bool(_evaluate(a, env)) for a in args)
    if op == "Not":
        return not bool(_evaluate(args[0], env))

    # arithmetic
    if op == "Add":
        return _evaluate(args[0], env) + _evaluate(args[1], env)  # type: ignore[operator]
    if op == "Sub":
        return _evaluate(args[0], env) - _evaluate(args[1], env)  # type: ignore[operator]
    if op == "Mul":
        return _evaluate(args[0], env) * _evaluate(args[1], env)  # type: ignore[operator]
    if op == "Div":
        return _evaluate(args[0], env) / _evaluate(args[1], env)  # type: ignore[operator]
    if op == "Mod":
        return _evaluate(args[0], env) % _evaluate(args[1], env)  # type: ignore[operator]
    if op == "Neg":
        return -_evaluate(args[0], env)  # type: ignore[operator]

    # length-style helpers (axioms about collection sizes are common)
    if op == "Len":
        return len(_evaluate(args[0], env))  # type: ignore[arg-type]
    if op == "Head":
        seq = cast("Sequence[FieldValue]", _evaluate(args[0], env))
        return seq[0]
    if op == "Tail":
        seq = cast("Sequence[FieldValue]", _evaluate(args[0], env))
        return cast("EvalResult", list(seq[1:]))
    if op == "Abs":
        return abs(_evaluate(args[0], env))  # type: ignore[arg-type]

    # list / string concatenation: ``a ++ b``
    if op == "Concat":
        a = _evaluate(args[0], env)
        b = _evaluate(args[1], env)
        return a + b  # type: ignore[operator]

    # map / filter: each takes a one-arg function as its first argument.
    # The function is either an identifier (looked up in
    # ``_APP_BUILTINS_BY_NAME``) or a ``Lam``.
    if op == "Map":
        func_node, seq_node = args[0], args[1]
        seq = cast("Sequence[FieldValue]", _evaluate(seq_node, env))
        return cast("EvalResult", [_apply_unary(func_node, item, env) for item in seq])
    if op == "Filter":
        func_node, seq_node = args[0], args[1]
        seq = cast("Sequence[FieldValue]", _evaluate(seq_node, env))
        return cast(
            "EvalResult",
            [item for item in seq if bool(_apply_unary(func_node, item, env))],
        )

    # Edge: ``a -> "b"`` parses to ``Builtin('Edge', [Var a, Lit "b"])``.
    # In an axiom expression this is a graph-shape predicate that
    # rarely shows up; treat it as the underlying string ``b``.
    if op == "Edge":
        return _evaluate(args[1], env)

    msg = f"axiom evaluator does not yet implement Builtin {op!r}"
    raise NotImplementedError(msg)


def _apply_unary(
    func_node: ExprNode, value: FieldValue, env: dict[str, FieldValue]
) -> EvalResult:
    """Apply a one-argument function (identifier or lambda) to ``value``."""
    match func_node:
        case {"Lam": (str(param), body)} | {"Lam": [str(param), body]}:
            new_env = dict(env)
            new_env[param] = value
            return _evaluate(body, new_env)
        case {"Var": str(name)} if name in _APP_BUILTINS_BY_NAME:
            return _APP_BUILTINS_BY_NAME[name]([value])
        case {"Var": "not"}:
            return not bool(value)
        case _:
            msg = (
                "axiom map/filter function must be a lambda or known "
                f"builtin name; got {func_node!r}"
            )
            raise NotImplementedError(msg)


def check_class_axioms(cls: type, env: dict[str, FieldValue]) -> list[str]:
    """Run every collected axiom on ``cls`` against ``env``.

    Parameters
    ----------
    cls
        A [Model][didactic.api.Model] subclass with ``__class_axioms__``.
    env
        The field-name to value mapping.

    Returns
    -------
    list of str
        Failure messages, one per axiom that does not hold. Empty
        when every axiom holds.
    """
    failures: list[str] = []
    axioms: tuple[Axiom, ...] = getattr(cls, "__class_axioms__", ())
    for ax in axioms:
        try:
            predicate = parse_axiom_predicate(ax)
            ok = predicate(env)
        except (NameError, NotImplementedError) as exc:
            failures.append(f"axiom {ax.expr!r}: cannot evaluate ({exc})")
            continue
        if not ok:
            msg = ax.message or f"axiom failed: {ax.expr}"
            failures.append(msg)
    return failures


__all__ = [
    "check_class_axioms",
    "parse_axiom_predicate",
]
