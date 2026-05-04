"""Axiom enforcement: parse axiom strings into predicates run at construction.

Each ``__axioms__`` entry is parsed into a panproto ``Expr`` AST via
``panproto.parse_expr``, then evaluated against a Model instance's
field values during construction. Failures raise
[didactic.api.ValidationError][didactic.api.ValidationError] with the axiom's
message.

The evaluator walks the panproto Expr ``to_dict()`` form, which is a
tagged union of ``{"Builtin": ...}``, ``{"Var": ...}``, ``{"Lit": ...}``,
and a small set of other variants.

See Also
--------
didactic.axioms._axioms : the Axiom record type and ``__axioms__`` collection.
panproto.parse_expr : the underlying parser.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

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


def parse_axiom_predicate(axiom: Axiom):  # type: ignore[no-untyped-def]
    """Parse an axiom expression into a callable predicate.

    Parameters
    ----------
    axiom
        An [Axiom][didactic.api.Axiom] instance whose ``expr`` is the
        Haskell-style surface syntax accepted by
        ``panproto.parse_expr``.

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

    expr = panproto.parse_expr(axiom.expr)
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

    The function handles the common subset that shows up in axiom
    expressions: variable lookup, literals, comparison operators,
    boolean connectives, and arithmetic. Unrecognised node shapes
    raise ``NotImplementedError``.

    Pattern-matched on the panproto Expr shape: each variant is
    a single-key dict whose value has a known structure. The match
    statements narrow the dynamic ``ExprNode`` shape into the typed
    sub-shapes the helpers consume.
    """
    match node:
        case {"Var": str(name)}:
            if name not in env:
                msg = f"axiom references unbound variable {name!r}"
                raise NameError(msg)
            return env[name]
        case {"Lit": dict(lit)}:
            return _evaluate_literal(lit)
        case {"Builtin": [str(op), list(args)]}:
            return _evaluate_builtin(op, args, env)
        case {"App": [dict(func), arg]}:
            # general App: rare in axioms; treat as a builtin family if
            # head is a Var pointing at a known function name
            if "Var" in func and isinstance(func["Var"], str):
                return _evaluate_builtin(func["Var"], [arg], env)
            msg = f"App nodes with non-Var heads are not supported: {func!r}"
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

    msg = f"axiom evaluator does not yet implement Builtin {op!r}"
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
