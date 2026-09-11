"""Declaration and checking surface for generalized algebraic theories."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, cast

from didactic.gadt._ast import (
    App,
    Case,
    Let,
    SortExpr,
    Term,
    Var,
    check_name,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    import panproto

    from didactic.types._typing import JsonObject, JsonValue


class GADTDeclarationError(ValueError):
    """A locally detectable error in a GADT declaration."""


class GADTReductionError(RuntimeError):
    """A symbolic reduction could not make safe progress."""


@dataclass(frozen=True, slots=True)
class Parameter:
    """One named input in a sort or operation telescope."""

    name: str
    sort: SortExpr
    implicit: bool = False

    def __post_init__(self) -> None:
        check_name(self.name, "parameter name")

    def to_sort_param_spec(self) -> JsonObject:
        """Render a sort parameter for Panproto."""
        return {"name": self.name, "sort": self.sort.to_spec()}

    def to_input_spec(self) -> JsonValue:
        """Render an operation input for Panproto."""
        return [self.name, self.sort.to_spec(), "Yes" if self.implicit else "No"]


def param(name: str, sort: SortExpr, *, implicit: bool = False) -> Parameter:
    """Construct a named parameter."""
    return Parameter(name, sort, implicit)


def _empty_constructor_names() -> list[str]:
    """Return a precisely typed empty constructor registry."""
    return []


@dataclass(eq=False, slots=True)
class Family:
    """A possibly indexed sort declaration owned by one :class:`GADT`."""

    owner: GADT
    name: str
    parameters: tuple[Parameter, ...]
    closed: bool
    kind: JsonValue = "Structural"
    _constructors: list[str] = field(
        default_factory=_empty_constructor_names, repr=False
    )

    def __post_init__(self) -> None:
        check_name(self.name, "family name")
        parameter_names = [item.name for item in self.parameters]
        if len(set(parameter_names)) != len(parameter_names):
            msg = f"family {self.name!r} contains duplicate parameter names"
            raise GADTDeclarationError(msg)

    def __call__(self, *indices: Term) -> SortExpr:
        """Apply this family to exactly its declared number of indices."""
        if len(indices) != len(self.parameters):
            msg = (
                f"family {self.name!r} expects {len(self.parameters)} indices, "
                f"got {len(indices)}"
            )
            raise GADTDeclarationError(msg)
        return SortExpr(self.name, tuple(indices))

    @property
    def constructors(self) -> tuple[str, ...]:
        """Return constructor names in declaration order."""
        return tuple(self._constructors)

    def to_spec(self) -> JsonObject:
        """Render this family as a Panproto sort declaration."""
        closure: JsonValue = (
            {"Closed": list(self._constructors)} if self.closed else "Open"
        )
        return {
            "name": self.name,
            "params": [item.to_sort_param_spec() for item in self.parameters],
            "kind": self.kind,
            "closure": closure,
        }

    def add_constructor(self, name: str) -> None:
        """Record an owner-validated constructor in declaration order."""
        self._constructors.append(name)


@dataclass(frozen=True, slots=True)
class Motive:
    """The result-sort expression of an eliminator.

    A motive may mention any earlier eliminator input. Panproto refines those
    variables separately in each case branch, which is what permits branch
    bodies at different indices to inhabit one dependent result.
    """

    result: SortExpr

    def at(self, **substitution: Term) -> SortExpr:
        """Instantiate motive variables with concrete index terms."""
        return self.result.substitute(substitution)


@dataclass(eq=False, slots=True)
class Operation:
    """A constructor, ordinary operation, or eliminator declaration."""

    owner: GADT
    name: str
    inputs: tuple[Parameter, ...]
    output: SortExpr
    role: Literal["constructor", "operation", "eliminator"] = "operation"
    motive: Motive | None = None

    def __post_init__(self) -> None:
        check_name(self.name, f"{self.role} name")
        input_names = [item.name for item in self.inputs]
        if len(set(input_names)) != len(input_names):
            msg = f"operation {self.name!r} contains duplicate input names"
            raise GADTDeclarationError(msg)
        if self.role == "eliminator" and self.motive is None:
            raise GADTDeclarationError("an eliminator requires an explicit motive")
        if self.role != "eliminator" and self.motive is not None:
            raise GADTDeclarationError("only an eliminator may carry a motive")

    @property
    def explicit_inputs(self) -> tuple[Parameter, ...]:
        """Return the arguments callers must supply in term applications."""
        return tuple(item for item in self.inputs if not item.implicit)

    def __call__(self, *args: Term) -> App:
        """Construct a checked-arity symbolic application."""
        expected = len(self.explicit_inputs)
        if len(args) != expected:
            msg = (
                f"operation {self.name!r} expects {expected} explicit args, "
                f"got {len(args)}"
            )
            raise GADTDeclarationError(msg)
        return App(self.name, tuple(args))

    def to_spec(self) -> JsonObject:
        """Render this operation for Panproto."""
        return {
            "name": self.name,
            "inputs": [item.to_input_spec() for item in self.inputs],
            "output": self.output.to_spec(),
        }

    def define(
        self,
        body: Term,
        *,
        name: str | None = None,
        lhs_args: tuple[Term, ...] | None = None,
    ) -> Equation:
        """Define an eliminator by an oriented, typechecked equation.

        The equation is included among the ordinary equalities sent to
        Panproto and among Didactic's executable reduction rules. By default,
        its left side applies the eliminator to variables named after every
        explicit input.
        """
        if self.role != "eliminator":
            msg = f"operation {self.name!r} is not an eliminator"
            raise GADTDeclarationError(msg)
        if lhs_args is None:
            lhs_args = tuple(Var(item.name) for item in self.explicit_inputs)
        lhs = self(*lhs_args)
        equation_name = name or f"{self.name}_def_{self.owner.definition_count}"
        return self.owner.equation(equation_name, lhs, body, executable=True)


@dataclass(frozen=True, slots=True)
class Equation:
    """A named equality between terms."""

    name: str
    lhs: Term
    rhs: Term
    directed: bool = False

    def __post_init__(self) -> None:
        check_name(self.name, "equation name")

    def to_spec(self) -> JsonObject:
        """Render the equality for Panproto."""
        return {
            "name": self.name,
            "lhs": self.lhs.to_spec(),
            "rhs": self.rhs.to_spec(),
        }


class GADT:
    """A complete generalized algebraic theory declaration.

    ``GADT`` is a builder with a deliberate freeze point. Sorts, constructors,
    operations, and equations may be added until :meth:`compile` is called.
    Compilation seals the declaration, builds a ``panproto.Theory`` value, and
    runs Panproto's full theory typechecker before returning it.
    """

    def __init__(self, name: str, *, extends: Iterable[str] = ()) -> None:
        self.name = check_name(name, "theory name")
        self.extends = tuple(
            check_name(item, "extended theory name") for item in extends
        )
        self._families: dict[str, Family] = {}
        self._operations: dict[str, Operation] = {}
        self._equations: dict[str, Equation] = {}
        self._directed_equations: dict[str, Equation] = {}
        self._definitions: list[Equation] = []
        self._sealed = False
        self._theory_cache: panproto.Theory | None = None

    @property
    def sealed(self) -> bool:
        """Whether compilation has frozen the declaration."""
        return self._sealed

    @property
    def families(self) -> tuple[Family, ...]:
        """Return families in declaration order."""
        return tuple(self._families.values())

    @property
    def operations(self) -> tuple[Operation, ...]:
        """Return operations in declaration order."""
        return tuple(self._operations.values())

    @property
    def equations(self) -> tuple[Equation, ...]:
        """Return ordinary equations in declaration order."""
        return tuple(self._equations.values())

    @property
    def definition_count(self) -> int:
        """Return the number used to derive the next definition name."""
        return len(self._definitions)

    def _require_open(self) -> None:
        if self._sealed:
            msg = f"GADT {self.name!r} is sealed and cannot be modified"
            raise GADTDeclarationError(msg)

    def sort(
        self,
        name: str,
        *,
        parameters: Iterable[Parameter] = (),
        closed: bool = False,
        kind: JsonValue = "Structural",
    ) -> Family:
        """Declare a plain or indexed sort."""
        self._require_open()
        if name in self._families:
            raise GADTDeclarationError(f"sort {name!r} is already declared")
        family = Family(self, name, tuple(parameters), closed, kind)
        self._families[name] = family
        return family

    family = sort

    def constructor(
        self,
        name: str,
        *,
        inputs: Iterable[Parameter] = (),
        result: SortExpr,
    ) -> Operation:
        """Declare an introduction form for a family."""
        family = self._families.get(result.name)
        if family is None:
            msg = f"constructor {name!r} returns undeclared family {result.name!r}"
            raise GADTDeclarationError(msg)
        operation = self._add_operation(name, tuple(inputs), result, "constructor")
        family.add_constructor(name)
        return operation

    def operation(
        self,
        name: str,
        *,
        inputs: Iterable[Parameter] = (),
        result: SortExpr,
    ) -> Operation:
        """Declare an ordinary operation."""
        return self._add_operation(name, tuple(inputs), result, "operation")

    def eliminator(
        self,
        name: str,
        *,
        inputs: Iterable[Parameter],
        motive: Motive | SortExpr,
    ) -> Operation:
        """Declare an operation whose equations eliminate a family."""
        resolved = motive if isinstance(motive, Motive) else Motive(motive)
        return self._add_operation(
            name,
            tuple(inputs),
            resolved.result,
            "eliminator",
            resolved,
        )

    def _add_operation(
        self,
        name: str,
        inputs: tuple[Parameter, ...],
        result: SortExpr,
        role: Literal["constructor", "operation", "eliminator"],
        motive: Motive | None = None,
    ) -> Operation:
        self._require_open()
        if name in self._operations:
            raise GADTDeclarationError(f"operation {name!r} is already declared")
        family = self._families.get(result.name)
        if family is None:
            msg = f"operation {name!r} returns undeclared sort {result.name!r}"
            raise GADTDeclarationError(msg)
        if family.closed and role != "constructor":
            msg = (
                f"non-constructor operation {name!r} cannot return closed "
                f"family {family.name!r}"
            )
            raise GADTDeclarationError(msg)
        operation = Operation(self, name, inputs, result, role, motive)
        self._operations[name] = operation
        return operation

    def equation(
        self,
        name: str,
        lhs: Term,
        rhs: Term,
        *,
        directed: bool = False,
        executable: bool = False,
    ) -> Equation:
        """Declare an equality or directed rewrite."""
        self._require_open()
        table = self._directed_equations if directed else self._equations
        if name in self._equations or name in self._directed_equations:
            raise GADTDeclarationError(f"equation {name!r} is already declared")
        equation = Equation(name, lhs, rhs, directed)
        table[name] = equation
        if executable or directed:
            self._definitions.append(equation)
        return equation

    def rewrite(self, name: str, lhs: Term, rhs: Term) -> Equation:
        """Declare a directed equation used by normalization."""
        return self.equation(name, lhs, rhs, directed=True, executable=True)

    def to_spec(self) -> JsonObject:
        """Return the complete Panproto theory specification."""
        return {
            "name": self.name,
            "extends": list(self.extends),
            "sorts": [family.to_spec() for family in self._families.values()],
            "ops": [operation.to_spec() for operation in self._operations.values()],
            "eqs": [equation.to_spec() for equation in self._equations.values()],
            "directed_eqs": [
                equation.to_spec() for equation in self._directed_equations.values()
            ],
            "policies": [],
        }

    def compile(self) -> panproto.Theory:
        """Build and rigorously typecheck a ``panproto.Theory``."""
        if self._theory_cache is not None:
            return self._theory_cache
        import panproto  # noqa: PLC0415

        payload = cast("Mapping[str, JsonValue]", self.to_spec())
        theory = panproto.create_theory(payload)
        panproto.typecheck_theory(theory)
        self._sealed = True
        self._theory_cache = theory
        return theory

    @property
    def theory(self) -> panproto.Theory:
        """Compile once and return the cached Panproto theory."""
        return self.compile()

    def infer_sort(
        self,
        term: Term,
        *,
        context: Mapping[str, SortExpr] | None = None,
    ) -> SortExpr:
        """Infer the sort of an application, variable, let, or case term."""
        environment = {} if context is None else dict(context)
        if isinstance(term, Var):
            try:
                return environment[term.name]
            except KeyError:
                msg = f"unbound variable {term.name!r}"
                raise GADTDeclarationError(msg) from None
        if isinstance(term, App):
            return self._infer_application(term, environment)
        if isinstance(term, Let):
            bound_sort = self.infer_sort(term.bound, context=environment)
            environment[term.name] = bound_sort
            return self.infer_sort(term.body, context=environment)
        if isinstance(term, Case):
            return self._infer_case(term, environment)
        raise GADTDeclarationError("a typed hole has no inferable concrete sort")

    def _infer_application(
        self, term: App, context: Mapping[str, SortExpr]
    ) -> SortExpr:
        try:
            operation = self._operations[term.op]
        except KeyError:
            msg = f"unknown operation {term.op!r}"
            raise GADTDeclarationError(msg) from None
        if len(term.args) != len(operation.explicit_inputs):
            msg = (
                f"operation {term.op!r} expects {len(operation.explicit_inputs)} "
                f"explicit args, got {len(term.args)}"
            )
            raise GADTDeclarationError(msg)
        substitution: dict[str, Term] = {}
        argument_iter = iter(term.args)
        for input_parameter in operation.inputs:
            if input_parameter.implicit:
                continue
            argument = next(argument_iter)
            actual = self.infer_sort(argument, context=context)
            expected = input_parameter.sort.substitute(substitution)
            _unify_sort(expected, actual, substitution)
            substitution[input_parameter.name] = argument
        unresolved = operation.output.free_vars().difference(substitution)
        if unresolved:
            names = ", ".join(sorted(unresolved))
            msg = f"cannot infer output indices {names} for operation {term.op!r}"
            raise GADTDeclarationError(msg)
        return operation.output.substitute(substitution)

    def _infer_case(self, term: Case, context: Mapping[str, SortExpr]) -> SortExpr:
        if not term.branches:
            raise GADTDeclarationError("cannot infer the sort of an empty case")
        scrutinee_sort = self.infer_sort(term.scrutinee, context=context)
        inferred: SortExpr | None = None
        for case_branch in term.branches:
            constructor = self._operations.get(case_branch.constructor)
            if constructor is None or constructor.role != "constructor":
                msg = f"unknown constructor {case_branch.constructor!r}"
                raise GADTDeclarationError(msg)
            if len(case_branch.binders) != len(constructor.inputs):
                msg = (
                    f"branch {case_branch.constructor!r} expects "
                    f"{len(constructor.inputs)} binders, got {len(case_branch.binders)}"
                )
                raise GADTDeclarationError(msg)
            substitution: dict[str, Term] = {}
            _unify_sort(constructor.output, scrutinee_sort, substitution)
            branch_context = dict(context)
            binder_refinements: dict[str, Term] = {}
            for binder_name, input_parameter in zip(
                case_branch.binders, constructor.inputs, strict=True
            ):
                branch_context[binder_name] = input_parameter.sort.substitute(
                    substitution
                )
                refined = substitution.get(input_parameter.name)
                if refined is None:
                    substitution[input_parameter.name] = Var(binder_name)
                else:
                    binder_refinements[binder_name] = refined
            branch_sort = self.infer_sort(case_branch.body, context=branch_context)
            branch_sort = branch_sort.substitute(binder_refinements)
            escaping = branch_sort.free_vars().intersection(case_branch.binders)
            if escaping:
                names = ", ".join(sorted(escaping))
                msg = f"branch-local variables escape case result sort: {names}"
                raise GADTDeclarationError(msg)
            if inferred is None:
                inferred = branch_sort
            elif inferred != branch_sort:
                msg = (
                    f"case branches infer different sorts: {inferred} and {branch_sort}"
                )
                raise GADTDeclarationError(msg)
        assert inferred is not None
        return inferred

    def normalize(self, term: Term, *, max_steps: int = 1_000) -> Term:
        """Normalize a symbolic term with eliminator definitions and rewrites."""
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        current = term
        for _ in range(max_steps):
            current, changed = self._reduce_once(current)
            if not changed:
                return current
        msg = f"normalization exceeded {max_steps} steps"
        raise GADTReductionError(msg)

    def _reduce_once(self, term: Term) -> tuple[Term, bool]:
        if isinstance(term, Let):
            return term.body.substitute({term.name: term.bound}), True
        if isinstance(term, Case):
            return self._reduce_case(term)
        if isinstance(term, App):
            return self._reduce_app(term)
        return term, False

    def _reduce_case(self, term: Case) -> tuple[Term, bool]:
        scrutinee, changed = self._reduce_once(term.scrutinee)
        if changed:
            return Case(scrutinee, term.branches), True
        if not isinstance(scrutinee, App):
            return term, False
        for case_branch in term.branches:
            if case_branch.constructor != scrutinee.op:
                continue
            constructor = self._operations.get(scrutinee.op)
            if constructor is None:
                return term, False
            arguments = self._all_application_arguments(constructor, scrutinee)
            if len(case_branch.binders) != len(arguments):
                msg = (
                    f"branch {case_branch.constructor!r} binds "
                    f"{len(case_branch.binders)} values but the term carries "
                    f"{len(arguments)}"
                )
                raise GADTReductionError(msg)
            subst = dict(zip(case_branch.binders, arguments, strict=True))
            return case_branch.body.substitute(subst), True
        return term, False

    def _all_application_arguments(
        self, operation: Operation, application: App
    ) -> tuple[Term, ...]:
        """Recover inferred arguments so a case can bind the full telescope."""
        if len(application.args) == len(operation.inputs):
            return application.args
        substitution: dict[str, Term] = {}
        slots: list[Term | None] = []
        explicit = iter(application.args)
        for input_parameter in operation.inputs:
            if input_parameter.implicit:
                slots.append(None)
                continue
            argument = next(explicit)
            actual = self.infer_sort(argument)
            expected = input_parameter.sort.substitute(substitution)
            _unify_sort(expected, actual, substitution)
            substitution[input_parameter.name] = argument
            slots.append(argument)
        resolved: list[Term] = []
        for input_parameter, argument in zip(operation.inputs, slots, strict=True):
            if argument is not None:
                resolved.append(argument)
                continue
            inferred = substitution.get(input_parameter.name)
            if inferred is None:
                msg = (
                    f"cannot recover implicit argument {input_parameter.name!r} "
                    f"while reducing {operation.name!r}"
                )
                raise GADTReductionError(msg)
            resolved.append(inferred)
        return tuple(resolved)

    def _reduce_app(self, term: App) -> tuple[Term, bool]:
        for index, argument in enumerate(term.args):
            reduced, changed = self._reduce_once(argument)
            if changed:
                args = list(term.args)
                args[index] = reduced
                return App(term.op, tuple(args)), True
        for definition in self._definitions:
            substitution: dict[str, Term] = {}
            if _match(definition.lhs, term, substitution):
                return definition.rhs.substitute(substitution), True
        return term, False

    def __repr__(self) -> str:
        return (
            f"GADT({self.name!r}, families={len(self._families)}, "
            f"operations={len(self._operations)}, equations="
            f"{len(self._equations) + len(self._directed_equations)})"
        )


def _match(pattern: Term, value: Term, substitution: dict[str, Term]) -> bool:
    if isinstance(pattern, Var):
        existing = substitution.get(pattern.name)
        if existing is None:
            substitution[pattern.name] = value
            return True
        return existing == value
    if isinstance(pattern, App) and isinstance(value, App):
        return (
            pattern.op == value.op
            and len(pattern.args) == len(value.args)
            and all(
                _match(left, right, substitution)
                for left, right in zip(pattern.args, value.args, strict=True)
            )
        )
    return pattern == value


def _unify_sort(
    expected: SortExpr,
    actual: SortExpr,
    substitution: dict[str, Term],
) -> None:
    if expected.name != actual.name or len(expected.args) != len(actual.args):
        msg = f"sort mismatch: expected {expected}, got {actual}"
        raise GADTDeclarationError(msg)
    for expected_arg, actual_arg in zip(expected.args, actual.args, strict=True):
        if not _unify_term(expected_arg, actual_arg, substitution):
            msg = f"index mismatch: expected {expected}, got {actual}"
            raise GADTDeclarationError(msg)


def _unify_term(
    expected: Term,
    actual: Term,
    substitution: dict[str, Term],
) -> bool:
    if isinstance(expected, Var):
        bound = substitution.get(expected.name)
        if bound is None:
            substitution[expected.name] = actual
            return True
        return bound == actual
    if isinstance(expected, App) and isinstance(actual, App):
        return (
            expected.op == actual.op
            and len(expected.args) == len(actual.args)
            and all(
                _unify_term(left, right, substitution)
                for left, right in zip(expected.args, actual.args, strict=True)
            )
        )
    return expected == actual


__all__ = [
    "GADT",
    "Equation",
    "Family",
    "GADTDeclarationError",
    "GADTReductionError",
    "Motive",
    "Operation",
    "Parameter",
    "param",
]
