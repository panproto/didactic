"""Typed abstract syntax for generalized algebraic theories.

The classes in this module mirror Panproto's term and sort-expression
representations exactly, while keeping construction and substitution on the
Python side type-safe. They are deliberately small immutable values: a term
can be used as a dictionary key, embedded in an indexed field declaration, or
serialized into a Theory specification without a lossy text-parsing step.
"""

from __future__ import annotations

import keyword
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

    from didactic.types._typing import JsonObject, JsonValue


def check_name(name: str, what: str = "name") -> str:
    """Return a valid GAT identifier or raise a precise error."""
    if not name or not name.isidentifier() or keyword.iskeyword(name):
        msg = f"{what} must be a valid non-keyword identifier; got {name!r}"
        raise ValueError(msg)
    return name


class Term(ABC):
    """Base class for terms in a generalized algebraic theory."""

    @abstractmethod
    def to_spec(self) -> JsonObject:
        """Return Panproto's JSON-serializable representation."""

    @abstractmethod
    def substitute(self, _substitution: Mapping[str, Term]) -> Term:
        """Apply a capture-avoiding variable substitution."""

    @abstractmethod
    def free_vars(self) -> frozenset[str]:
        """Return the names free in this term."""


@dataclass(frozen=True, slots=True)
class Var(Term):
    """A variable reference."""

    name: str

    def __post_init__(self) -> None:
        check_name(self.name, "variable name")

    def to_spec(self) -> JsonObject:
        """Return the tagged variable record Panproto accepts."""
        return {"Var": self.name}

    def substitute(self, substitution: Mapping[str, Term]) -> Term:
        """Replace this variable when it occurs in ``substitution``."""
        return substitution.get(self.name, self)

    def free_vars(self) -> frozenset[str]:
        """Return this variable as the sole free name."""
        return frozenset((self.name,))

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class App(Term):
    """An operation applied to zero or more argument terms."""

    op: str
    args: tuple[Term, ...] = ()

    def __post_init__(self) -> None:
        check_name(self.op, "operation name")

    def to_spec(self) -> JsonObject:
        """Return the tagged application record Panproto accepts."""
        return {
            "App": {
                "op": self.op,
                "args": [arg.to_spec() for arg in self.args],
            }
        }

    def substitute(self, substitution: Mapping[str, Term]) -> Term:
        """Substitute recursively through the arguments."""
        return App(self.op, tuple(arg.substitute(substitution) for arg in self.args))

    def free_vars(self) -> frozenset[str]:
        """Return the union of the arguments' free variables."""
        names: set[str] = set()
        for argument in self.args:
            names.update(argument.free_vars())
        return frozenset(names)

    def __str__(self) -> str:
        rendered = ", ".join(str(arg) for arg in self.args)
        return f"{self.op}({rendered})"


@dataclass(frozen=True, slots=True)
class Hole(Term):
    """A typed hole reported by Panproto during theory checking."""

    name: str | None = None

    def __post_init__(self) -> None:
        if self.name is not None:
            check_name(self.name, "hole name")

    def to_spec(self) -> JsonObject:
        """Return the tagged hole record Panproto accepts."""
        return {"Hole": {"name": self.name}}

    def substitute(self, _substitution: Mapping[str, Term]) -> Term:
        """Return the hole unchanged; holes do not bind variables."""
        return self

    def free_vars(self) -> frozenset[str]:
        """Return the empty set."""
        return frozenset()

    def __str__(self) -> str:
        return "?" if self.name is None else f"?{self.name}"


@dataclass(frozen=True, slots=True)
class Branch:
    """One constructor branch of a case term."""

    constructor: str
    binders: tuple[str, ...]
    body: Term

    def __post_init__(self) -> None:
        check_name(self.constructor, "constructor name")
        for binder_name in self.binders:
            check_name(binder_name, "branch binder")
        if len(set(self.binders)) != len(self.binders):
            msg = f"branch {self.constructor!r} contains duplicate binders"
            raise ValueError(msg)

    def to_spec(self) -> JsonObject:
        """Return Panproto's case-branch representation."""
        return {
            "constructor": self.constructor,
            "binders": list(self.binders),
            "body": self.body.to_spec(),
        }


@dataclass(frozen=True, slots=True)
class Case(Term):
    """Exhaustive elimination of a closed-sort term."""

    scrutinee: Term
    branches: tuple[Branch, ...]

    def __post_init__(self) -> None:
        names = [branch.constructor for branch in self.branches]
        if len(set(names)) != len(names):
            msg = "a case cannot contain two branches for the same constructor"
            raise ValueError(msg)

    def to_spec(self) -> JsonObject:
        """Return the tagged case record Panproto accepts."""
        return {
            "Case": {
                "scrutinee": self.scrutinee.to_spec(),
                "branches": [branch.to_spec() for branch in self.branches],
            }
        }

    def substitute(self, substitution: Mapping[str, Term]) -> Term:
        """Substitute without replacing variables shadowed by branch binders."""
        new_branches: list[Branch] = []
        for case_branch in self.branches:
            inner = {
                name: value
                for name, value in substitution.items()
                if name not in case_branch.binders
            }
            binders = list(case_branch.binders)
            body = case_branch.body
            image_vars = _substitution_image_vars(inner, body.free_vars())
            avoid = set(body.free_vars()) | image_vars | set(inner)
            for index, binder_name in enumerate(binders):
                if binder_name not in image_vars:
                    continue
                fresh = _fresh_name(binder_name, avoid)
                body = body.substitute({binder_name: Var(fresh)})
                binders[index] = fresh
                avoid.add(fresh)
            new_branches.append(
                Branch(
                    case_branch.constructor,
                    tuple(binders),
                    body.substitute(inner),
                )
            )
        return Case(self.scrutinee.substitute(substitution), tuple(new_branches))

    def free_vars(self) -> frozenset[str]:
        """Return free names after removing each branch's binders."""
        names = set(self.scrutinee.free_vars())
        for case_branch in self.branches:
            names.update(case_branch.body.free_vars().difference(case_branch.binders))
        return frozenset(names)

    def __str__(self) -> str:
        rendered = "; ".join(
            f"{item.constructor}({', '.join(item.binders)}) => {item.body}"
            for item in self.branches
        )
        return f"case {self.scrutinee} of {rendered}"


@dataclass(frozen=True, slots=True)
class Let(Term):
    """A monomorphic local binding."""

    name: str
    bound: Term
    body: Term

    def __post_init__(self) -> None:
        check_name(self.name, "let binder")

    def to_spec(self) -> JsonObject:
        """Return the tagged let record Panproto accepts."""
        return {
            "Let": {
                "name": self.name,
                "bound": self.bound.to_spec(),
                "body": self.body.to_spec(),
            }
        }

    def substitute(self, substitution: Mapping[str, Term]) -> Term:
        """Substitute outside the scope of the local binder."""
        inner = {k: value for k, value in substitution.items() if k != self.name}
        binder_name = self.name
        body = self.body
        image_vars = _substitution_image_vars(inner, body.free_vars())
        if binder_name in image_vars:
            avoid = set(body.free_vars()) | image_vars | set(inner)
            fresh = _fresh_name(binder_name, avoid)
            body = body.substitute({binder_name: Var(fresh)})
            binder_name = fresh
        return Let(
            binder_name,
            self.bound.substitute(substitution),
            body.substitute(inner),
        )

    def free_vars(self) -> frozenset[str]:
        """Return free names, excluding the locally bound name."""
        return self.bound.free_vars() | self.body.free_vars().difference((self.name,))

    def __str__(self) -> str:
        return f"let {self.name} = {self.bound} in {self.body}"


@dataclass(frozen=True, slots=True)
class SortExpr:
    """A sort head applied to zero or more term indices."""

    name: str
    args: tuple[Term, ...] = ()

    def __post_init__(self) -> None:
        check_name(self.name, "sort name")

    def to_spec(self) -> JsonValue:
        """Return a bare name or Panproto's applied-sort record."""
        if not self.args:
            return self.name
        return {"name": self.name, "args": [arg.to_spec() for arg in self.args]}

    def substitute(self, substitution: Mapping[str, Term]) -> SortExpr:
        """Substitute throughout the sort's term indices."""
        return SortExpr(
            self.name,
            tuple(arg.substitute(substitution) for arg in self.args),
        )

    def free_vars(self) -> frozenset[str]:
        """Return free names in the index arguments."""
        names: set[str] = set()
        for argument in self.args:
            names.update(argument.free_vars())
        return frozenset(names)

    def __str__(self) -> str:
        if not self.args:
            return self.name
        return f"{self.name}({', '.join(str(arg) for arg in self.args)})"


def _substitution_image_vars(
    substitution: Mapping[str, Term], body_vars: frozenset[str]
) -> set[str]:
    """Return free variables introduced at substitution sites in a body."""
    names: set[str] = set()
    for variable_name, replacement in substitution.items():
        if variable_name in body_vars:
            names.update(replacement.free_vars())
    return names


def _fresh_name(stem: str, avoid: set[str]) -> str:
    """Choose a deterministic valid binder name outside ``avoid``."""
    suffix = 1
    while f"{stem}_{suffix}" in avoid:
        suffix += 1
    return f"{stem}_{suffix}"


def term_from_spec(spec: JsonValue) -> Term:
    """Decode a term previously produced by :meth:`Term.to_spec`.

    Parameters
    ----------
    spec
        A tagged Panproto term record.

    Returns
    -------
    Term
        The corresponding immutable term.
    """
    if not isinstance(spec, dict) or len(spec) != 1:
        msg = f"term spec must be a one-key object; got {spec!r}"
        raise TypeError(msg)
    if "Var" in spec:
        name = spec["Var"]
        if not isinstance(name, str):
            raise TypeError("Var payload must be a string")
        return Var(name)
    if "App" in spec:
        return _app_from_spec(spec["App"])
    if "Hole" in spec:
        payload = spec["Hole"]
        if not isinstance(payload, dict):
            raise TypeError("Hole payload must be an object")
        name = payload.get("name")
        if name is not None and not isinstance(name, str):
            raise TypeError("Hole name must be a string or null")
        return Hole(name)
    if "Let" in spec:
        return _let_from_spec(spec["Let"])
    if "Case" in spec:
        return _case_from_spec(spec["Case"])
    msg = f"unknown term variant {next(iter(spec))!r}"
    raise ValueError(msg)


def _app_from_spec(payload: JsonValue) -> App:
    if not isinstance(payload, dict):
        raise TypeError("App payload must be an object")
    op = payload.get("op")
    args = payload.get("args")
    if not isinstance(op, str) or not isinstance(args, list):
        raise TypeError("App requires a string op and list args")
    return App(op, tuple(term_from_spec(arg) for arg in args))


def _let_from_spec(payload: JsonValue) -> Let:
    if not isinstance(payload, dict):
        raise TypeError("Let payload must be an object")
    name = payload.get("name")
    if not isinstance(name, str):
        raise TypeError("Let name must be a string")
    return Let(
        name,
        term_from_spec(cast("JsonValue", payload.get("bound"))),
        term_from_spec(cast("JsonValue", payload.get("body"))),
    )


def _case_from_spec(payload: JsonValue) -> Case:
    if not isinstance(payload, dict):
        raise TypeError("Case payload must be an object")
    branch_specs = payload.get("branches")
    if not isinstance(branch_specs, list):
        raise TypeError("Case branches must be a list")
    decoded = tuple(_branch_from_spec(raw_branch) for raw_branch in branch_specs)
    return Case(
        term_from_spec(cast("JsonValue", payload.get("scrutinee"))),
        decoded,
    )


def _branch_from_spec(payload: JsonValue) -> Branch:
    if not isinstance(payload, dict):
        raise TypeError("case branch must be an object")
    constructor = payload.get("constructor")
    binders = payload.get("binders")
    if not isinstance(constructor, str) or not isinstance(binders, list):
        raise TypeError("case branch requires constructor and binders")
    if not all(isinstance(item, str) for item in binders):
        raise TypeError("case binders must be strings")
    return Branch(
        constructor,
        tuple(cast("list[str]", binders)),
        term_from_spec(cast("JsonValue", payload.get("body"))),
    )


def var(name: str) -> Var:
    """Construct a variable term."""
    return Var(name)


def app(operation: str, *args: Term) -> App:
    """Construct an operation application."""
    return App(operation, tuple(args))


def hole(name: str | None = None) -> Hole:
    """Construct a typed hole."""
    return Hole(name)


def branch(constructor: str, *binders: str, body: Term) -> Branch:
    """Construct a case branch."""
    return Branch(constructor, tuple(binders), body)


def case(scrutinee: Term, *branches: Branch) -> Case:
    """Construct a case-analysis term."""
    return Case(scrutinee, tuple(branches))


def let(name: str, bound: Term, body: Term) -> Let:
    """Construct a local let-binding."""
    return Let(name, bound, body)


__all__ = [
    "App",
    "Branch",
    "Case",
    "Hole",
    "Let",
    "SortExpr",
    "Term",
    "Var",
    "app",
    "branch",
    "case",
    "hole",
    "let",
    "term_from_spec",
    "var",
]
