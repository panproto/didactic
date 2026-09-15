"""Telescopes from keyword arguments, and terms from traced lambdas.

A declaration names its inputs as keyword arguments, in order, each with a
sort::

    lang.constructor("IntLit", value=El[int_code()], returns=Expr[int_code()])

A sort that depends on an earlier input is a lambda over the earlier names::

    lang.eliminator(
        "evaluate", t=Ty, expression=lambda t: Expr[t], returns=lambda t: El[t]
    )

The lambda's parameter names say which earlier inputs it needs, and it is
run once with a symbolic variable for each.

Terms are built the same way. :func:`match` takes one keyword per
constructor whose value is a lambda over that constructor's binders, and
an eliminator's body is a lambda over its inputs. Nothing is parsed: each
lambda runs once and returns the term it describes, and every binder is a
real Python name. An :class:`Operation` may stand in for a lambda that
would only apply it to the binders, so ``unil=ufallback`` reads as
``unil=lambda: ufallback()``.

Every callable here is typed as a union over arities so that a strict
type checker infers each lambda parameter as :class:`Var` rather than
leaving it unknown.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, TypeIs

from didactic.gadt._ast import Branch, Case, Let, SortExpr, Term, Var
from didactic.gadt._errors import GADTDeclarationError

if TYPE_CHECKING:
    from didactic.gadt._declarations import GADT, Family, Operation, Parameter

MAX_ARITY: Final = 8
"""How many binders a lambda may declare and still be typed precisely.

Longer lambdas run, since the binders are read at runtime, but a strict
type checker will not infer their parameter types.
"""

type Sort = SortExpr | Family
"""A sort given directly: an applied family such as ``Expr[t]`` or a bare
family with no indices such as ``Ty``."""

type Dep[R] = (
    Callable[[Var], R]
    | Callable[[Var, Var], R]
    | Callable[[Var, Var, Var], R]
    | Callable[[Var, Var, Var, Var], R]
    | Callable[[Var, Var, Var, Var, Var], R]
    | Callable[[Var, Var, Var, Var, Var, Var], R]
    | Callable[[Var, Var, Var, Var, Var, Var, Var], R]
    | Callable[[Var, Var, Var, Var, Var, Var, Var, Var], R]
)
"""A value that depends on earlier binders, as a lambda over their names."""

type SortSpec = Sort | Dep[Sort]
"""A sort, or a lambda over earlier inputs producing one."""

type InputSpec = SortSpec | Implicit
"""What one keyword argument of a declaration may be."""

type Body = (
    Operation
    | Callable[[], Term]
    | Callable[[Var], Term]
    | Callable[[Var, Var], Term]
    | Callable[[Var, Var, Var], Term]
    | Callable[[Var, Var, Var, Var], Term]
    | Callable[[Var, Var, Var, Var, Var], Term]
    | Callable[[Var, Var, Var, Var, Var, Var], Term]
    | Callable[[Var, Var, Var, Var, Var, Var, Var], Term]
    | Callable[[Var, Var, Var, Var, Var, Var, Var, Var], Term]
)
"""A term over some binders: an eliminator body, a case branch, a let body."""


@dataclass(frozen=True, slots=True)
class Implicit:
    """An input Panproto infers from the explicit ones: ``n=Implicit(Nat)``.

    The wrapped sort may itself depend on earlier inputs.
    """

    sort: SortSpec


def as_sort(value: object, *, what: str) -> SortExpr:
    """Coerce a declared sort to a sort expression.

    A :class:`SortExpr` passes through. A family with no parameters stands
    for its own sort. Anything else is an error naming what was expected.
    """
    from didactic.gadt._declarations import Family  # noqa: PLC0415

    if isinstance(value, SortExpr):
        return value
    if isinstance(value, Family):
        if value.parameters:
            arity = len(value.parameters)
            msg = (
                f"{what}: family {value.name!r} takes {arity} "
                f"{'index' if arity == 1 else 'indices'}; write "
                f"{value.name}[...] to apply it"
            )
            raise GADTDeclarationError(msg)
        return value()
    msg = (
        f"{what} must be a sort (a family such as `Ty`, an applied family "
        f"such as `Expr[t]`, or a lambda over earlier inputs producing one); "
        f"got {value!r}"
    )
    raise GADTDeclarationError(msg)


def resolve_sort(spec: object, bound: Mapping[str, Var], *, what: str) -> SortExpr:
    """Resolve a sort spec, running a dependence lambda over earlier binders.

    A lambda's parameter names must each be an earlier input; the message
    on a miss lists what is in scope, so a misspelt dependency fails at the
    declaration rather than as an unbound variable later.
    """
    if callable(spec) and not _is_family(spec):
        names = binders_of(spec, what=what)
        missing = [name for name in names if name not in bound]
        if missing:
            available = ", ".join(bound) or "(none)"
            msg = (
                f"{what}: depends on {', '.join(repr(m) for m in missing)}, "
                f"which is not an earlier input; earlier inputs are {available}"
            )
            raise GADTDeclarationError(msg)
        produced = spec(*(bound[name] for name in names))
        return as_sort(produced, what=what)
    return as_sort(spec, what=what)


def resolve_inputs(inputs: Mapping[str, object], *, what: str) -> tuple[Parameter, ...]:
    """Turn ordered keyword inputs into a telescope.

    Keyword order is declaration order, and each input's sort may depend on
    any input before it.
    """
    from didactic.gadt._declarations import Parameter  # noqa: PLC0415

    bound: dict[str, Var] = {}
    resolved: list[Parameter] = []
    for name, spec in inputs.items():
        implicit = isinstance(spec, Implicit)
        sort_spec = spec.sort if isinstance(spec, Implicit) else spec
        sort = resolve_sort(sort_spec, bound, what=f"{what}: input {name!r}")
        resolved.append(Parameter(name, sort, implicit))
        bound[name] = Var(name)
    return tuple(resolved)


def binders_of(fn: Callable[..., Any], *, what: str) -> tuple[str, ...]:
    """Read a body's binder names: a lambda's parameters, or an operation's inputs.

    An operation given as a body stands for applying it to its explicit
    inputs, so those input names are its binders.
    """
    if _is_operation(fn):
        return tuple(item.name for item in fn.explicit_inputs)
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError) as error:
        msg = f"{what}: expected a lambda or function, got {fn!r}"
        raise GADTDeclarationError(msg) from error
    names: list[str] = []
    for parameter in signature.parameters.values():
        if parameter.kind not in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            msg = (
                f"{what}: binders must be plain positional parameters, not {parameter}"
            )
            raise GADTDeclarationError(msg)
        names.append(parameter.name)
    return tuple(names)


@dataclass(frozen=True, slots=True)
class _Trace:
    """What a body may consult while it runs."""

    gadt: GADT
    environment: Mapping[str, SortExpr]


_TRACE: ContextVar[_Trace | None] = ContextVar("didactic_gadt_trace", default=None)


def trace_body(
    body: Callable[..., Any],
    gadt: GADT,
    inputs: tuple[Parameter, ...],
    *,
    what: str,
) -> Term:
    """Run an eliminator body once over its inputs and return its term.

    The body's parameters must name every input, in order, so a body that
    has drifted from its declaration fails here rather than binding the
    wrong variable.
    """
    expected = tuple(item.name for item in inputs)
    names = binders_of(body, what=what)
    if names != expected:
        msg = (
            f"{what}: body parameters {list(names)} must be the inputs in "
            f"order, {list(expected)}"
        )
        raise GADTDeclarationError(msg)
    environment = {item.name: item.sort for item in inputs}
    token = _TRACE.set(_Trace(gadt, environment))
    try:
        produced = body(*(Var(name) for name in names))
    finally:
        _TRACE.reset(token)
    return _require_term(produced, what=f"{what}: body")


def match(scrutinee: Term, **branches: Body) -> Case:
    """Case analysis, one keyword per constructor: ``IntLit=lambda v: v``.

    Each branch lambda runs once with a fresh variable per parameter, and
    its parameters are the branch's binders. Inside an eliminator body the
    constructor names are checked against the scrutinee's family at once,
    naming the valid set on a miss, and each branch's binder count against
    its constructor. Outside one, those are left to Panproto's checker.
    """
    if not branches:
        raise GADTDeclarationError("match() needs at least one branch")
    trace = _TRACE.get()
    allowed = _constructors_of(scrutinee, trace)
    built: list[Branch] = []
    for constructor, body_fn in branches.items():
        if allowed is not None and constructor not in allowed:
            expected = ", ".join(allowed) or "(none)"
            msg = (
                f"match(): {constructor!r} is not a constructor of the "
                f"scrutinee's family; expected one of {expected}"
            )
            raise GADTDeclarationError(msg)
        binders = binders_of(body_fn, what=f"match(): branch {constructor!r}")
        if trace is not None:
            _check_arity(trace.gadt, constructor, binders)
        body = _require_term(
            body_fn(*(Var(name) for name in binders)),
            what=f"match(): branch {constructor!r}",
        )
        built.append(Branch(constructor, binders, body))
    return Case(scrutinee, tuple(built))


def let(bound: Term, body: Callable[[Var], Term] | Operation) -> Let:
    """Bind a term locally: ``let(int_value(), lambda x: IntLit(x))``.

    The lambda's single parameter is the binder. A unary operation may
    stand in for the lambda: ``let(int_value(), IntLit)``.
    """
    names = binders_of(body, what="let()")
    if len(names) != 1:
        msg = f"let(): body must bind exactly one name; got {list(names)}"
        raise GADTDeclarationError(msg)
    return Let(names[0], bound, _require_term(body(Var(names[0])), what="let(): body"))


def _require_term(value: object, *, what: str) -> Term:
    """Check a traced body's result at runtime.

    The signatures promise a term, but a body is ordinary Python and an
    untyped caller can return anything; this is where that is caught.
    """
    if not isinstance(value, Term):
        msg = f"{what} must return a term; got {value!r}"
        raise GADTDeclarationError(msg)
    return value


def _is_family(value: object) -> TypeIs[Family]:
    from didactic.gadt._declarations import Family  # noqa: PLC0415

    return isinstance(value, Family)


def _is_operation(value: object) -> TypeIs[Operation]:
    from didactic.gadt._declarations import Operation  # noqa: PLC0415

    return isinstance(value, Operation)


def _constructors_of(scrutinee: Term, trace: _Trace | None) -> tuple[str, ...] | None:
    if trace is None:
        return None
    try:
        sort = trace.gadt.infer_sort(scrutinee, context=trace.environment)
    except GADTDeclarationError:
        return None
    family = trace.gadt.family_named(sort.name)
    return family.constructors if family is not None and family.closed else None


def _check_arity(gadt: GADT, constructor: str, binders: tuple[str, ...]) -> None:
    operation = gadt.operation_named(constructor)
    if operation is None:
        return
    expected = len(operation.inputs)
    if len(binders) != expected:
        msg = (
            f"match(): branch {constructor!r} binds {len(binders)} "
            f"{'name' if len(binders) == 1 else 'names'} but the constructor "
            f"has {expected} {'input' if expected == 1 else 'inputs'}"
        )
        raise GADTDeclarationError(msg)


__all__ = [
    "MAX_ARITY",
    "Body",
    "Dep",
    "Implicit",
    "InputSpec",
    "Sort",
    "SortSpec",
    "as_sort",
    "binders_of",
    "let",
    "match",
    "resolve_inputs",
    "resolve_sort",
    "trace_body",
]
