"""Indexed Model fields and the schema-oriented universe convenience layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Union, cast

from didactic.gadt._ast import App, SortExpr, Term, Var
from didactic.gadt._declarations import GADT, Family, GADTDeclarationError, param

if TYPE_CHECKING:
    from collections.abc import Mapping

    import panproto

    from didactic.fields._fields import FieldSpec
    from didactic.models._model import Model
    from didactic.types._types import TypeForm
    from didactic.types._typing import FieldValue


@dataclass(frozen=True, slots=True)
class IndexedBy:
    """Metadata linking a field's sort to one or more sibling fields.

    Put an ``IndexedBy`` value inside ``typing.Annotated``. The base Python
    annotation remains visible to static type checkers, while this marker
    supplies the dependent family and the model fields used as its indices.
    Optional ``cases`` associate concrete index terms with Python annotations,
    allowing runtime values to be validated at the refined type.
    """

    family: Family
    index_fields: tuple[str, ...]
    cases: tuple[tuple[tuple[Term, ...], TypeForm], ...] = ()
    case_labels: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        if len(self.index_fields) != len(self.family.parameters):
            msg = (
                f"indexed family {self.family.name!r} expects "
                f"{len(self.family.parameters)} indices, got "
                f"{len(self.index_fields)} field names"
            )
            raise GADTDeclarationError(msg)
        if len(set(self.index_fields)) != len(self.index_fields):
            raise GADTDeclarationError("indexed field names must be unique")
        for field_name in self.index_fields:
            if not field_name.isidentifier():
                msg = f"index field name must be an identifier; got {field_name!r}"
                raise GADTDeclarationError(msg)
        seen: set[tuple[Term, ...]] = set()
        for indices, _ in self.cases:
            if len(indices) != len(self.index_fields):
                msg = (
                    f"case for {self.family.name!r} has {len(indices)} indices; "
                    f"expected {len(self.index_fields)}"
                )
                raise GADTDeclarationError(msg)
            if indices in seen:
                raise GADTDeclarationError(f"duplicate indexed case {indices!r}")
            seen.add(indices)
        if self.case_labels and len(self.case_labels) != len(self.cases):
            raise GADTDeclarationError(
                "indexed case labels must correspond one-to-one with cases"
            )
        seen_labels: set[tuple[str, ...]] = set()
        for labels in self.case_labels:
            if len(labels) != len(self.index_fields):
                msg = (
                    f"case label has {len(labels)} indices; "
                    f"expected {len(self.index_fields)}"
                )
                raise GADTDeclarationError(msg)
            if labels in seen_labels:
                raise GADTDeclarationError(f"duplicate indexed case label {labels!r}")
            seen_labels.add(labels)

    @property
    def sort(self) -> SortExpr:
        """Return the symbolic field sort before model values are substituted."""
        return self.family(*(Var(field_name) for field_name in self.index_fields))

    def instantiate(self, values: Mapping[str, FieldValue]) -> SortExpr:
        """Substitute concrete sibling-field values into the dependent sort."""
        indices = self._indices(values)
        return self.family(*indices)

    def expected_python_type(self, values: Mapping[str, FieldValue]) -> TypeForm | None:
        """Return the Python payload type selected by concrete indices."""
        indices = self._indices(values)
        normalized = tuple(self.family.owner.normalize(item) for item in indices)
        for case_indices, annotation in self.cases:
            candidate = tuple(
                self.family.owner.normalize(item) for item in case_indices
            )
            if candidate == normalized:
                return annotation
        return None

    def validate(self, values: Mapping[str, FieldValue], value: FieldValue) -> None:
        """Check a symbolic or Python payload against its instantiated index."""
        expected_sort = self.instantiate(values)
        if isinstance(value, Term):
            actual_sort = self.family.owner.infer_sort(value)
            if _normalize_sort(self.family.owner, actual_sort) != _normalize_sort(
                self.family.owner, expected_sort
            ):
                msg = f"expected {expected_sort}, got term of sort {actual_sort}"
                raise ValueError(msg)
            return
        selected = self.expected_python_type(values)
        if selected is None:
            rendered = ", ".join(
                str(_index_term(values[name])) for name in self.index_fields
            )
            msg = f"no Python payload case for {self.family.name}({rendered})"
            raise ValueError(msg)
        from didactic.types._types import classify  # noqa: PLC0415

        # Running the selected encoder performs the same exact validation as a
        # normal field, but against the index-refined arm rather than the
        # wider union visible in the annotation.
        try:
            classify(selected).encode(value)
        except AssertionError:
            msg = (
                f"value {value!r} does not inhabit the Python payload type "
                f"selected by {expected_sort}"
            )
            raise TypeError(msg) from None

    def _indices(self, values: Mapping[str, FieldValue]) -> tuple[Term, ...]:
        """Resolve runtime labels or symbolic terms to family indices."""
        raw = tuple(values[field_name] for field_name in self.index_fields)
        resolved: tuple[Term, ...] | None = None
        if self.case_labels and all(isinstance(item, str) for item in raw):
            labels = cast("tuple[str, ...]", raw)
            for candidate, (indices, _) in zip(
                self.case_labels, self.cases, strict=True
            ):
                if candidate == labels:
                    resolved = indices
                    break
        if resolved is None:
            resolved = tuple(_index_term(item) for item in raw)

        substitution: dict[str, Term] = {}
        for field_name, index, parameter in zip(
            self.index_fields, resolved, self.family.parameters, strict=True
        ):
            expected = parameter.sort.substitute(substitution)
            actual = self.family.owner.infer_sort(index)
            if _normalize_sort(self.family.owner, actual) != _normalize_sort(
                self.family.owner, expected
            ):
                msg = (
                    f"index field {field_name!r} expects sort {expected}, "
                    f"got term of sort {actual}"
                )
                raise TypeError(msg)
            substitution[parameter.name] = index
        return resolved


def indexed_by(
    family: Family,
    *index_fields: str,
    cases: Mapping[Term | tuple[Term, ...], TypeForm] | None = None,
) -> IndexedBy:
    """Construct an :class:`IndexedBy` marker.

    A one-index family accepts term keys directly. Multi-index families use a
    tuple of terms per case.
    """
    normalized: list[tuple[tuple[Term, ...], TypeForm]] = []
    if cases is not None:
        for key, annotation in cases.items():
            indices = key if isinstance(key, tuple) else (key,)
            normalized.append((indices, annotation))
    return IndexedBy(family, tuple(index_fields), tuple(normalized))


class Universe:
    """A finite Tarski universe for value-indexed schema fields.

    The generated GADT contains a closed code sort and an open ``El(code)``
    carrier. Each supplied case receives a nullary code constructor, a value
    sort, and an injection from that value sort into the corresponding
    carrier. The open carrier permits Model field projections while the closed
    code sort retains exhaustive case analysis.
    """

    def __init__(self, name: str, **cases: TypeForm) -> None:
        if not cases:
            raise GADTDeclarationError("a universe requires at least one code")
        self.name = name
        self.gadt = GADT(name)
        self.codes = self.gadt.sort(f"{name}Code", closed=True)
        self.elements = self.gadt.family(
            f"{name}El",
            parameters=(param("code", self.codes()),),
        )
        self._python_cases = dict(cases)
        self._code_terms: dict[str, App] = {}
        for code_name, annotation in cases.items():
            code_operation = self.gadt.constructor(
                f"{name}_{code_name}", result=self.codes()
            )
            code_term = code_operation()
            self._code_terms[code_name] = code_term
            value_sort = self.gadt.sort(
                f"{name}_{code_name}_value",
                kind={"Val": _value_kind(annotation)},
            )
            self.gadt.operation(
                f"{name}_{code_name}_value",
                inputs=(param("value", value_sort()),),
                result=self.elements(code_term),
            )

        # Runtime conveniences. They are intentionally attributes rather than
        # promises to static type checkers; callers who need static precision
        # write the equivalent Literal/union annotation explicitly.
        self.Code = cast("TypeForm", Literal[tuple(cases)])
        self.Value = cast(
            "TypeForm",
            Union[tuple(cases.values())],  # noqa: UP007 - runtime-built union
        )

    def code(self, name: str) -> App:
        """Return the nullary term for one universe code."""
        try:
            return self._code_terms[name]
        except KeyError:
            expected = ", ".join(self._code_terms)
            msg = f"unknown code {name!r}; expected one of {expected}"
            raise KeyError(msg) from None

    def at(self, field_name: str) -> IndexedBy:
        """Build a one-index marker selecting payload type by code field."""
        cases = tuple(
            ((term,), self._python_cases[name])
            for name, term in self._code_terms.items()
        )
        labels = tuple((name,) for name in self._code_terms)
        return IndexedBy(self.elements, (field_name,), cases, labels)

    @property
    def theory(self) -> panproto.Theory:
        """Compile and return this universe's checked theory."""
        return self.gadt.theory

    def __repr__(self) -> str:
        return f"Universe({self.name!r}, codes={tuple(self._code_terms)!r})"


def indexed_marker(spec: FieldSpec) -> IndexedBy | None:
    """Return the ``IndexedBy`` metadata attached to a field, if any."""
    marker = spec.extras.get("IndexedBy")
    return marker if isinstance(marker, IndexedBy) else None


def validate_model_index_declarations(cls: type[Model]) -> None:
    """Reject missing references and cyclic indexed-field dependencies."""
    specs = cls.__field_specs__
    graph: dict[str, tuple[str, ...]] = {}
    for field_name, spec in specs.items():
        marker = indexed_marker(spec)
        if marker is None:
            continue
        missing = [name for name in marker.index_fields if name not in specs]
        if missing:
            names = ", ".join(repr(item) for item in missing)
            msg = f"indexed field {field_name!r} refers to missing fields: {names}"
            raise GADTDeclarationError(msg)
        graph[field_name] = marker.index_fields

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            raise GADTDeclarationError(
                f"indexed field dependency cycle contains {name!r}"
            )
        visiting.add(name)
        for dependency in graph.get(name, ()):
            if dependency in graph:
                visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for field_name in graph:
        visit(field_name)


def validate_model_indices(model: Model) -> tuple[tuple[str, str], ...]:
    """Return ``(field, message)`` entries for failed indexed invariants."""
    marked = tuple(
        (field_name, marker)
        for field_name, spec in type(model).__field_specs__.items()
        if (marker := indexed_marker(spec)) is not None
    )
    if not marked:
        return ()
    values = {name: getattr(model, name) for name in type(model).__field_specs__}
    failures: list[tuple[str, str]] = []
    for field_name, marker in marked:
        try:
            marker.validate(values, values[field_name])
        except (TypeError, ValueError, GADTDeclarationError) as exc:
            failures.append((field_name, str(exc)))
    return tuple(failures)


def _index_term(value: FieldValue) -> Term:
    if isinstance(value, Term):
        return value
    if isinstance(value, str) and value.isidentifier():
        return App(value)
    msg = (
        "an index field must contain a GADT Term or an identifier string; "
        f"got {type(value).__name__}"
    )
    raise TypeError(msg)


def _normalize_sort(theory: GADT, sort: SortExpr) -> SortExpr:
    return SortExpr(sort.name, tuple(theory.normalize(item) for item in sort.args))


def _value_kind(annotation: TypeForm) -> str:
    from didactic.types._types import classify  # noqa: PLC0415

    sort = classify(annotation).sort
    return {
        "String": "Str",
        "Int": "Int",
        "Float64": "Float",
        "Decimal": "Float",
        "Bool": "Bool",
        "Bytes": "Bytes",
    }.get(sort, "Str")


__all__ = [
    "IndexedBy",
    "Universe",
    "indexed_by",
]
