"""Field descriptors, the ``dx.field(...)`` constructor, and FieldSpec.

A ``Model`` subclass declares fields as type-annotated class attributes.
At class-creation time, the metaclass ([didactic.models._meta][]) walks each
annotation and produces a [FieldSpec][didactic.api.FieldSpec] capturing the
sort name, encoder/decoder, default, and any axioms induced by
``Annotated[...]`` metadata.

User-facing API
---------------
[Field][didactic.api.Field]
    The field-descriptor class. Returned by [field][didactic.api.field] when
    a user writes ``foo: int = field(default=0)``.
[field][didactic.api.field]
    The field-constructor function. Mirrors ``dataclasses.field`` and
    Pydantic's ``Field`` with panproto-native extensions.
[FieldSpec][didactic.api.FieldSpec]
    The metaclass-produced record describing a fully resolved field.

Notes
-----
Both ``Field`` (the class) and ``field`` (the function) are passed in
``field_specifiers=...`` on ``@dataclass_transform`` so type checkers
understand them as field descriptors.

See Also
--------
didactic.types._types : the translation primitives FieldSpec uses.
didactic.models._meta : the metaclass that consumes FieldSpec.
"""

# ``field()`` uses the field-specifier overload pattern from
# ``CONTRIBUTING.md`` carve-out 1: typed overloads return ``T`` so
# call sites like ``email: str = dx.field(description="...")`` type-check,
# while the implementation returns ``Field``. Pyright in strict mode
# rejects this inconsistency between the unconstrained-``T`` overload
# returns and the concrete ``Field`` impl return; no structural fix
# preserves the surface ergonomics. Confined to this file.
# pyright: reportInconsistentOverload=false
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _dc_field
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Final,
    ForwardRef,
    Literal,
    Self,
    TypeVar,
    cast,
    get_args,
    get_origin,
    overload,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from didactic.types._types import TypeForm, TypeTranslation
    from didactic.types._typing import (
        DefaultOrMissing,
        FieldValue,
        Opaque,
    )

# ---------------------------------------------------------------------------
# The `field` overloads below are the **only** place in didactic where
# `Any` appears in an annotation. The escape hatch is needed because
# `pyright` (in strict mode) does not unwrap field-specifier return
# types when checking ``required: str = field(description=...)``: the
# descriptor returned by `field()` is not assignable to `str`. The
# typeshed stubs for `dataclasses.field` use the same trick (one
# overload per (default | default_factory | required) shape, where the
# required-no-default variant returns `Any`). Mirroring that pattern
# here lets users write the natural ``foo: int = dx.field(default=0)``
# and ``required: str = dx.field(description="...")`` forms without
# pyright errors, without bleeding `Any` into the rest of the codebase.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------


class _Missing:
    """Sentinel for "no default supplied".

    Notes
    -----
    A class rather than a module-level instance so that pickling and
    repr both yield the same identity. ``MISSING`` is the singleton.
    """

    _instance: Self | None = None

    def __new__(cls) -> Self:
        """Return the canonical singleton."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        """Render as ``MISSING``."""
        return "MISSING"

    def __bool__(self) -> bool:
        """Treat the missing-default sentinel as falsy."""
        return False


MISSING: Final[_Missing] = _Missing()
#: Public alias for the sentinel type, exposed so other modules can write
#: ``isinstance(value, MissingType)`` without crossing a private boundary.
MissingType = _Missing

# ---------------------------------------------------------------------------
# The Field descriptor class
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Field:
    """Field descriptor produced by the [field][didactic.api.field] constructor.

    Field instances appear as the right-hand side of class-attribute
    assignments in a Model body::

        class User(dx.Model):
            id: str
            email: str = dx.field(description="primary contact")

    The metaclass extracts the configuration and produces a
    [FieldSpec][didactic.api.FieldSpec]; ``Field`` itself carries no runtime
    behaviour beyond holding the configuration values.

    Parameters
    ----------
    default
        Default value, or ``MISSING`` if no default. Mutually exclusive
        with ``default_factory``.
    default_factory
        Zero-argument callable returning a default value.
    converter
        PEP 712 converter. Runs *before* type validation and any
        ``@validates`` hooks.
    alias
        External name for serialisation (input/output rename).
    description
        Human-readable description; populates the Theory's field
        metadata. Equivalent to ``Annotated[T, typing.Doc(...)]`` (PEP 727).
    examples
        Example values for documentation and code generation.
    deprecated
        If ``True``, surfaces a deprecation warning at construction.
    nominal
        If ``True``, the field contributes to the model's vertex identity
        (used by panproto-vcs for stable blame across renames).
    constraint
        A constraint object; typically an ``annotated_types`` primitive.
        Equivalent to placing it in ``Annotated[T, ...]`` metadata.
    coercion
        A coercion lens or callable; stored on the FieldSpec for
        downstream tooling, not consumed by Model construction yet.
    usage_mode
        Field role: ``"readwrite"`` (default), ``"computed"``, or
        ``"materialised"``.
    extras
        Extra metadata for downstream tooling.

    See Also
    --------
    field : the function that returns ``Field`` instances.
    FieldSpec : the resolved record produced by the metaclass.
    """

    default: DefaultOrMissing = MISSING
    default_factory: Callable[[], FieldValue] | None = None
    converter: Callable[[FieldValue], FieldValue] | None = None
    alias: str | None = None
    description: str | None = None
    examples: tuple[FieldValue, ...] = ()
    deprecated: bool = False
    nominal: bool = False
    constraint: Opaque | None = None
    coercion: Callable[..., FieldValue] | None = None
    usage_mode: Literal["readwrite", "computed", "materialised"] = "readwrite"
    extras: Mapping[str, Opaque] | None = None

    def __post_init__(self) -> None:
        """Validate exclusive options."""
        if self.default is not MISSING and self.default_factory is not None:
            msg = "field(): supply at most one of `default` and `default_factory`."
            raise TypeError(msg)


@overload
def field[T](
    *,
    default: T,
    converter: Callable[[FieldValue], FieldValue] | None = ...,
    alias: str | None = ...,
    description: str | None = ...,
    examples: tuple[FieldValue, ...] = ...,
    deprecated: bool = ...,
    nominal: bool = ...,
    constraint: Opaque | None = ...,
    coercion: Callable[..., FieldValue] | None = ...,
    usage_mode: Literal["readwrite", "computed", "materialised"] = ...,
    extras: Mapping[str, Opaque] | None = ...,
) -> T: ...
@overload
def field[T](
    *,
    default_factory: Callable[[], T],
    converter: Callable[[FieldValue], FieldValue] | None = ...,
    alias: str | None = ...,
    description: str | None = ...,
    examples: tuple[FieldValue, ...] = ...,
    deprecated: bool = ...,
    nominal: bool = ...,
    constraint: Opaque | None = ...,
    coercion: Callable[..., FieldValue] | None = ...,
    usage_mode: Literal["readwrite", "computed", "materialised"] = ...,
    extras: Mapping[str, Opaque] | None = ...,
) -> T: ...
@overload
def field(
    *,
    converter: Callable[[FieldValue], FieldValue] | None = ...,
    alias: str | None = ...,
    description: str | None = ...,
    examples: tuple[FieldValue, ...] = ...,
    deprecated: bool = ...,
    nominal: bool = ...,
    constraint: Opaque | None = ...,
    coercion: Callable[..., FieldValue] | None = ...,
    usage_mode: Literal["readwrite", "computed", "materialised"] = ...,
    extras: Mapping[str, Opaque] | None = ...,
) -> Any: ...  # documented escape hatch for required-with-metadata fields
def field(
    *,
    default: FieldValue | _Missing = MISSING,
    default_factory: Callable[[], FieldValue] | None = None,
    converter: Callable[[FieldValue], FieldValue] | None = None,
    alias: str | None = None,
    description: str | None = None,
    examples: tuple[FieldValue, ...] = (),
    deprecated: bool = False,
    nominal: bool = False,
    constraint: Opaque | None = None,
    coercion: Callable[..., FieldValue] | None = None,
    usage_mode: Literal["readwrite", "computed", "materialised"] = "readwrite",
    extras: Mapping[str, Opaque] | None = None,
) -> Field:
    """Construct a [Field][didactic.api.Field] descriptor.

    Parameters
    ----------
    default
        Default value. If both ``default`` and ``default_factory`` are
        omitted, the field is required.
    default_factory
        Zero-argument callable returning a default. Mutually exclusive
        with ``default``.
    converter
        PEP 712 converter applied before type validation.
    alias
        Serialisation alias. Useful when JSON/TOML payloads use a
        different name than the Python attribute.
    description
        Human-readable field description. Populates Theory metadata.
    examples
        Example values for documentation and code generation.
    deprecated
        Mark the field as deprecated; warning emitted at construction.
    nominal
        If ``True``, contributes to vertex identity (see VCS docs).
    constraint
        Constraint metadata equivalent to placing it in ``Annotated[...]``.
    coercion
        A coercion lens or callable. Stored on the FieldSpec and
        available to downstream tooling, but the Model construction
        path does not yet route values through it.
    usage_mode
        Field role: ``"readwrite"`` | ``"computed"`` | ``"materialised"``.
    extras
        Extra metadata for downstream tooling.

    Returns
    -------
    Field
        A field descriptor. With the metaclass's ``@dataclass_transform``
        and the ``field_specifiers=(Field, field)`` declaration, type
        checkers accept ``foo: int = dx.field(...)`` because they
        recognise this as a synthesised default for the field.

    See Also
    --------
    Field : the descriptor class returned by this function.
    didactic.models._meta : the metaclass that consumes Fields and produces
        [FieldSpec][didactic.api.FieldSpec] records.

    Examples
    --------
    >>> import didactic.api as dx
    >>> class User(dx.Model):
    ...     id: str = dx.field(nominal=True, description="primary key")
    ...     email: str = dx.field(alias="email_address")
    """
    return Field(
        default=default,
        default_factory=default_factory,
        converter=converter,
        alias=alias,
        description=description,
        examples=examples,
        deprecated=deprecated,
        nominal=nominal,
        constraint=constraint,
        coercion=coercion,
        usage_mode=usage_mode,
        extras=extras,
    )


# ---------------------------------------------------------------------------
# FieldSpec; the resolved record
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """Fully resolved field record produced by the metaclass.

    A FieldSpec captures everything didactic needs to read or write one
    field: the sort name, the encode/decode pair, the default, the
    metadata, and any axioms induced by ``Annotated[...]`` constraints.

    Parameters
    ----------
    name
        The Python attribute name.
    annotation
        The original (resolved) type annotation.
    translation
        The result of running ``didactic.types._types.classify`` on the
        annotation.
    default
        The default value, or ``MISSING`` if the field is required.
    default_factory
        Zero-argument default-producing callable, or ``None``.
    converter
        PEP 712 converter applied before type validation.
    alias
        External serialisation name, or ``None``.
    description
        Field description (from ``dx.field(description=...)`` or PEP 727
        ``Doc``).
    examples
        Example values.
    deprecated
        Whether the field is deprecated.
    nominal
        Whether the field contributes to vertex identity.
    usage_mode
        Field role.
    axioms
        Axiom strings induced by ``Annotated[...]`` metadata. Each is a
        panproto-Expr-shaped predicate over the field's value.
    extras
        Unrecognised ``Annotated`` metadata, preserved for downstream tools.
    """

    name: str
    annotation: TypeForm | TypeVar | ForwardRef
    translation: TypeTranslation
    default: DefaultOrMissing = MISSING
    default_factory: Callable[[], FieldValue] | None = None
    converter: Callable[[FieldValue], FieldValue] | None = None
    alias: str | None = None
    description: str | None = None
    examples: tuple[FieldValue, ...] = ()
    deprecated: bool = False
    nominal: bool = False
    usage_mode: Literal["readwrite", "computed", "materialised"] = "readwrite"
    axioms: tuple[str, ...] = ()
    extras: Mapping[str, Opaque] = _dc_field(
        default_factory=lambda: cast("dict[str, Opaque]", {})
    )

    @property
    def is_required(self) -> bool:
        """Whether the field has no default and no default factory."""
        return self.default is MISSING and self.default_factory is None

    @property
    def sort(self) -> str:
        """The panproto sort name for this field's value type."""
        return self.translation.sort

    def make_default(self) -> DefaultOrMissing:
        """Produce a default value, calling the factory if present.

        Returns
        -------
        FieldValue or _Missing
            The default. ``MISSING`` if the field is required.
        """
        if self.default_factory is not None:
            return self.default_factory()
        return self.default


# ---------------------------------------------------------------------------
# Annotated metadata reader
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _AnnotatedRead:
    """Internal: the stuff we extract from an ``Annotated[...]`` annotation.

    Returned by
    [read_annotated_metadata][didactic.fields._fields.read_annotated_metadata].
    """

    description: str | None
    axioms: tuple[str, ...]
    constraints: tuple[Opaque, ...]  # the recognised constraint objects
    extras: dict[str, Opaque]


def _doc_text(meta: Opaque) -> str | None:
    """Extract documentation text from a PEP 727 ``typing.Doc`` instance.

    Returns ``None`` if the metadata is not a ``Doc``-shaped object.
    """
    # PEP 727 Doc has a `documentation: str` attribute. We duck-type to
    # avoid hard-coding the import path (it lives in `typing` on 3.14+
    # and `typing_extensions` for earlier versions, but didactic floors at
    # 3.14 so the typing path is canonical; but PEP 727 has gone through
    # naming churn, so duck-typing is safer than `isinstance`).
    text = getattr(meta, "documentation", None)
    if isinstance(text, str):
        return text
    return None


# dispatch table for annotated_types primitives. Each entry is
# (attribute name on the metadata object, axiom-template format string).
# We duck-type rather than import annotated_types eagerly so consumers
# can pass shape-compatible custom metadata.
_ANNOTATED_TYPES_DISPATCH: dict[str, tuple[str, str]] = {
    "Ge": ("ge", "x >= {!r}"),
    "Gt": ("gt", "x > {!r}"),
    "Le": ("le", "x <= {!r}"),
    "Lt": ("lt", "x < {!r}"),
    "MinLen": ("min_length", "len(x) >= {!r}"),
    "MaxLen": ("max_length", "len(x) <= {!r}"),
    "MultipleOf": ("multiple_of", "x % {!r} == 0"),
}


def _annotated_types_axiom(meta: Opaque) -> str | None:
    """Render one ``annotated_types`` primitive as a panproto-Expr string.

    This is a minimal first pass; only ``Ge``, ``Le``, ``Gt``, ``Lt``,
    ``MinLen``, ``MaxLen``, ``MultipleOf`` are recognised. Unknown
    objects from ``annotated_types`` fall through to ``extras``.

    Parameters
    ----------
    meta
        A metadata object pulled out of ``Annotated[T, ...]``.

    Returns
    -------
    str or None
        The rendered axiom or ``None`` if ``meta`` is not a recognised
        primitive.
    """
    spec = _ANNOTATED_TYPES_DISPATCH.get(type(meta).__name__)
    if spec is None:
        return None
    attr_name, template = spec
    if not hasattr(meta, attr_name):
        return None
    return template.format(getattr(meta, attr_name))


def read_annotated_metadata(annotation: Opaque) -> _AnnotatedRead:
    """Read description / axioms / extras out of an ``Annotated[...]`` annotation.

    Parameters
    ----------
    annotation
        Either an ``Annotated[T, ...]`` type or a plain type. For plain
        types, every field of the result is empty.

    Returns
    -------
    _AnnotatedRead
        Named-tuple-shaped result with description, axioms, constraints
        (the recognised metadata objects, kept for downstream use),
        and extras (everything we did not recognise).

    See Also
    --------
    didactic.types._types.unwrap_annotated : the underlying split.
    """
    if get_origin(annotation) is not Annotated:
        return _AnnotatedRead(description=None, axioms=(), constraints=(), extras={})

    args = get_args(annotation)
    metadata = tuple(args[1:])

    description: str | None = None
    axioms: list[str] = []
    constraints: list[Opaque] = []
    extras: dict[str, Opaque] = {}

    for meta in metadata:
        if (text := _doc_text(meta)) is not None:
            description = text
            continue
        if (axiom := _annotated_types_axiom(meta)) is not None:
            axioms.append(axiom)
            constraints.append(meta)
            continue
        # not recognised; preserve for downstream tools
        extras[type(meta).__name__] = meta

    return _AnnotatedRead(
        description=description,
        axioms=tuple(axioms),
        constraints=tuple(constraints),
        extras=extras,
    )


__all__ = [
    "MISSING",
    "Field",
    "FieldSpec",
    "field",
    "read_annotated_metadata",
]
