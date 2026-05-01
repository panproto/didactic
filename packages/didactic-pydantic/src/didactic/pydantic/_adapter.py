"""Pydantic v2 to didactic Model adapter.

The single user-facing entry point is [from_pydantic][didactic.pydantic.from_pydantic].
It walks a Pydantic ``BaseModel`` subclass's ``model_fields`` and produces
an equivalent [didactic.api.Model][didactic.api.Model] subclass.

Notes
-----
Mapping table (Pydantic FieldInfo on the left, didactic.field on the right)::

    annotation                    ->  class annotation
    default (PydanticUndefined)   ->  MISSING
    default_factory               ->  default_factory
    alias / validation_alias      ->  alias
    description                   ->  description
    examples                      ->  examples
    metadata (Annotated)          ->  passes through verbatim
    deprecated                    ->  deprecated
    init_var / repr (Pydantic)    ->  ignored (no didactic equivalent)
    json_schema_extra             ->  extras["json_schema_extra"]
    frozen                        ->  ignored (didactic Models are always frozen)

Pydantic features explicitly **not** translated:

- ``@field_validator`` / ``@model_validator``: keep on the Pydantic
  side or re-implement with [didactic.api.validates][didactic.api.validates].
- ``@computed_field``: re-author with [didactic.api.computed][didactic.api.computed].
- Discriminated unions: re-author with
  [didactic.api.TaggedUnion][didactic.api.TaggedUnion].

See Also
--------
didactic.Model : the base class produced by from_pydantic.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Annotated, cast

from pydantic_core import PydanticUndefined

import didactic.api as dx
from didactic.fields._fields import MISSING
from didactic.models._meta import ModelMeta
from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from didactic.types._typing import FieldValue, Opaque
    from pydantic.fields import FieldInfo


def from_pydantic(
    pyd_cls: type,
    *,
    name: str | None = None,
) -> type[dx.Model]:
    """Derive a [Model][didactic.api.Model] subclass from a Pydantic ``BaseModel``.

    Parameters
    ----------
    pyd_cls
        The Pydantic ``BaseModel`` subclass to translate.
    name
        Optional name for the new didactic class. Defaults to
        ``pyd_cls.__name__``.

    Returns
    -------
    type
        A new [didactic.api.Model][didactic.api.Model] subclass with one field per
        ``pyd_cls.model_fields`` entry.

    Raises
    ------
    TypeError
        If ``pyd_cls`` is not a Pydantic v2 ``BaseModel`` subclass.

    Notes
    -----
    The new class lives in the same module as ``pyd_cls`` (its
    ``__module__`` is set accordingly) so that any forward references
    inside its annotations resolve against the same globals.

    Examples
    --------
    >>> from pydantic import BaseModel, Field
    >>> class PydUser(BaseModel):
    ...     id: str
    ...     email: str = Field(description="primary contact")
    >>> User = from_pydantic(PydUser)
    >>> issubclass(User, dx.Model)
    True
    >>> u = User(id="u1", email="a@b.c")
    >>> u.email
    'a@b.c'
    """
    if not issubclass(pyd_cls, BaseModel):
        msg = (
            f"from_pydantic requires a Pydantic v2 BaseModel subclass; got {pyd_cls!r}"
        )
        raise TypeError(msg)

    target_name = name or pyd_cls.__name__
    annotations: dict[str, type] = {}
    namespace: dict[str, Opaque] = {}

    for fname, info in pyd_cls.model_fields.items():
        annotation = _resolve_annotation(info)
        annotations[fname] = annotation

        # we emit a dx.field(...) whenever there's any Pydantic-side metadata
        # to carry; default, factory, alias, description, examples, deprecated,
        # or json_schema_extra. Required fields with no metadata don't need a
        # didactic Field descriptor.
        if _has_metadata(info, PydanticUndefined):
            namespace[fname] = _to_dx_field(info, PydanticUndefined)

    namespace["__annotations__"] = annotations
    if pyd_cls.__doc__:
        namespace["__doc__"] = pyd_cls.__doc__
    namespace["__module__"] = pyd_cls.__module__

    cls = ModelMeta(target_name, (dx.Model,), namespace)
    return cast("type[dx.Model]", cls)


def _resolve_annotation(info: FieldInfo) -> type:
    """Reconstruct the original ``Annotated[...]`` annotation for a Pydantic field.

    Pydantic stores constraint metadata on ``info.metadata`` separately from
    the base annotation. The didactic metaclass expects these on the
    annotation itself (as ``Annotated[T, ...]``) so we splice them back in.

    Parameters
    ----------
    info
        The Pydantic ``FieldInfo`` for one field.

    Returns
    -------
    type
        Either the bare type or an ``Annotated[T, *metadata]`` form.
    """
    base = info.annotation
    if base is None:
        msg = "Pydantic FieldInfo has no annotation; cannot translate."
        raise TypeError(msg)
    metadata = tuple(info.metadata or ())
    if not metadata:
        return base
    return Annotated[base, *metadata]  # type: ignore[valid-type]


def _is_required(info: FieldInfo, undefined: Opaque) -> bool:
    """Whether the Pydantic field has no default and no factory."""
    has_default = info.default is not undefined
    has_factory = info.default_factory is not None
    return not (has_default or has_factory)


def _has_metadata(info: FieldInfo, undefined: Opaque) -> bool:
    """Whether the FieldInfo carries any metadata worth materialising as a Field.

    Returns
    -------
    bool
        ``True`` if any of: a default, a default_factory, an alias, a
        description, examples, the deprecated flag, or json_schema_extra
        are set.
    """
    return (
        info.default is not undefined
        or info.default_factory is not None
        or info.alias is not None
        or info.validation_alias is not None
        or info.description is not None
        or bool(info.examples)
        or bool(info.deprecated)
        or info.json_schema_extra is not None
    )


def _to_dx_field(info: FieldInfo, undefined: Opaque) -> dx.Field:
    """Translate one ``FieldInfo`` into a [didactic.api.field][didactic.api.field] call.

    Parameters
    ----------
    info
        The Pydantic ``FieldInfo``.
    undefined
        Pydantic's ``PydanticUndefined`` sentinel; passed in so we don't
        need to re-import it per call.

    Returns
    -------
    Field
        The didactic Field descriptor.
    """
    # Build a Field directly so each attribute is typed precisely; the
    # `field()` overloads are tuned for human-written class bodies, not
    # for kwargs-spreading from a heterogeneous source dict.
    extras: Mapping[str, Opaque] | None = None
    if info.json_schema_extra is not None and not callable(info.json_schema_extra):
        extras = {"json_schema_extra": dict(info.json_schema_extra)}

    raw_alias = info.alias if info.alias is not None else info.validation_alias
    alias = raw_alias if isinstance(raw_alias, str) else None

    examples: tuple[FieldValue, ...] = ()
    if info.examples:
        examples = tuple(_coerce_example(e) for e in info.examples)

    return dx.Field(
        default=info.default if info.default is not undefined else MISSING,
        default_factory=_coerce_factory(info.default_factory),
        alias=alias,
        description=info.description,
        examples=examples,
        deprecated=bool(info.deprecated),
        extras=extras,
    )


def _coerce_example(value: object) -> FieldValue:
    """Narrow an arbitrary Pydantic example value to ``FieldValue``.

    Pydantic stores examples as ``list[Any]``; didactic's ``examples``
    tuple is typed as ``tuple[FieldValue, ...]``. We accept the value
    structurally and let the metaclass / validation surface any real
    mismatch at class-construction time.
    """
    # FieldValue is a recursive union covering all JSON-shaped scalars,
    # tuples, frozensets, dicts, and Models. A runtime isinstance check
    # against the union would be expensive and brittle; the contract
    # here is "Pydantic gave us a value the user wrote as an example,
    # so we trust it as a FieldValue".
    if isinstance(value, (str, int, float, bool, bytes, type(None))):
        return value
    if isinstance(value, (tuple, list)):
        seq = cast("tuple[FieldValue, ...] | list[FieldValue]", value)
        return tuple(_coerce_example(v) for v in seq)
    if isinstance(value, dict):
        items = cast("dict[str, FieldValue]", value)
        return {str(k): _coerce_example(v) for k, v in items.items()}
    if isinstance(value, frozenset):
        members = cast("frozenset[FieldValue]", value)
        return frozenset(_coerce_example(v) for v in members)
    msg = f"Unsupported example value of type {type(value).__name__}: {value!r}"
    raise TypeError(msg)


def _coerce_factory(
    factory: object,
) -> Callable[[], FieldValue] | None:
    """Validate that a Pydantic ``default_factory`` is the zero-arg form.

    Pydantic v2 supports a one-arg ``default_factory(validated_data)`` form
    that didactic does not model; we only forward the zero-arg case. The
    returned object is the same callable, narrowed by an arity check so
    the static type ``Callable[[], FieldValue]`` is honest.
    """
    if factory is None:
        return None
    if not callable(factory):
        msg = f"default_factory must be callable, got {factory!r}"
        raise TypeError(msg)
    arity = _zero_arg_arity(factory)
    if not arity:
        msg = (
            "from_pydantic only supports zero-argument default_factory; "
            f"got a callable that requires arguments: {factory!r}"
        )
        raise TypeError(msg)
    # Pydantic types default_factory loosely (it returns ``Any`` and may
    # also accept a one-arg ``validated_data`` form). The arity check
    # above establishes the zero-arg contract didactic requires; we use
    # ``cast`` (the standard typed-Python narrowing primitive) to expose
    # the original callable under didactic's narrower signature without
    # wrapping, so identity is preserved (tests compare with ``is``).
    return cast("Callable[[], FieldValue]", factory)


def _zero_arg_arity(func: Callable[..., object]) -> bool:
    """Return ``True`` if ``func`` can be called with zero positional args."""
    try:
        sig = inspect.signature(func)
    except TypeError, ValueError:
        # Built-ins like ``tuple`` may not expose a signature; assume OK.
        return True
    for param in sig.parameters.values():
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        if param.default is inspect.Parameter.empty and param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            return False
    return True


__all__ = ["_is_required", "from_pydantic"]
