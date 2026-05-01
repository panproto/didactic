"""didactic Model to Pydantic v2 BaseModel adapter.

The single user-facing entry point is
[to_pydantic][didactic.pydantic.to_pydantic]. It walks a didactic
[Model][didactic.api.Model] subclass's ``__field_specs__`` and produces an
equivalent Pydantic ``BaseModel`` subclass, suitable for use with
FastAPI, OpenAPI generators, and any other Pydantic-shaped consumer.

Notes
-----
Mapping table (didactic FieldSpec on the left, Pydantic FieldInfo on the right)::

    annotation          ->  field annotation
    default (MISSING)   ->  PydanticUndefined  (required)
    default             ->  default
    default_factory     ->  default_factory
    alias               ->  alias / validation_alias / serialization_alias
    description         ->  description
    examples            ->  examples
    deprecated          ->  deprecated
    axioms (Annotated)  ->  passes through verbatim on the annotation
    extras              ->  json_schema_extra
    converter           ->  ignored (Pydantic doesn't have a direct equivalent)
    nominal             ->  ignored (Pydantic has no vertex-identity concept)
    usage_mode          ->  ignored

didactic concepts that have no clean Pydantic equivalent are dropped
silently:

- Computed fields ([didactic.api.computed][didactic.api.computed]) are dropped.
  Re-author with ``@computed_field`` on the Pydantic side if you need
  them.
- Tagged unions ([didactic.api.TaggedUnion][didactic.api.TaggedUnion]) are
  dropped. Re-author with Pydantic's discriminated unions.
- Validators ([didactic.api.validates][didactic.api.validates]) are dropped.
  Re-author with ``@field_validator`` / ``@model_validator``.

See Also
--------
didactic.pydantic.from_pydantic : the inverse direction.
didactic.Model : the input class.
"""

# Local PEP 695 type alias inside a function body and a heterogeneous
# kwargs dict for the dynamic-pydantic-Field construction.
# Tracked in panproto/didactic#1.
# pyright: reportArgumentType=false, reportGeneralTypeIssues=false

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, cast

import didactic.api as dx
from didactic.fields._fields import MISSING
from pydantic import BaseModel, Field, create_model

if TYPE_CHECKING:
    from collections.abc import Callable

    from didactic.fields._fields import FieldSpec
    from didactic.types._typing import FieldValue
    from pydantic.fields import FieldInfo


def to_pydantic(
    dx_cls: type[dx.Model],
    *,
    name: str | None = None,
) -> type[BaseModel]:
    """Derive a Pydantic ``BaseModel`` subclass from a didactic Model.

    Parameters
    ----------
    dx_cls
        The [didactic.api.Model][didactic.api.Model] subclass to translate.
    name
        Optional name for the new Pydantic class. Defaults to
        ``dx_cls.__name__``.

    Returns
    -------
    type
        A new Pydantic ``BaseModel`` subclass with one field per
        ``dx_cls.__field_specs__`` entry.

    Raises
    ------
    TypeError
        If ``dx_cls`` is not a [didactic.api.Model][didactic.api.Model] subclass.

    Notes
    -----
    The new class lives in the same module as ``dx_cls`` so that any
    forward references inside its annotations resolve against the same
    globals. Computed fields and tagged-union variants are skipped;
    only ``readwrite`` fields are translated.

    Examples
    --------
    >>> import didactic.api as dx
    >>> from didactic.pydantic import to_pydantic
    >>>
    >>> class User(dx.Model):
    ...     id: str
    ...     email: str = dx.field(description="primary contact")
    >>>
    >>> PydUser = to_pydantic(User)
    >>> issubclass(PydUser, BaseModel)
    True
    >>> u = PydUser(id="u1", email="a@b.c")
    >>> u.email
    'a@b.c'
    """
    # static type already says ``type[dx.Model]``; the runtime check
    # catches users who bypass type-checking and hand in a non-Model.
    if not (isinstance(dx_cls, type) and issubclass(dx_cls, dx.Model)):  # pyright: ignore[reportUnnecessaryIsInstance]
        msg = f"to_pydantic requires a didactic.Model subclass; got {dx_cls!r}"
        raise TypeError(msg)

    target_name = name or dx_cls.__name__
    fields: dict[str, tuple[type, FieldInfo]] = {}

    for fname, spec in dx_cls.__field_specs__.items():
        if spec.usage_mode != "readwrite":
            # computed and materialised fields don't translate cleanly;
            # they would need re-authoring as @computed_field on the
            # Pydantic side
            continue

        annotation = _annotation_with_axioms(spec)
        field_info = _to_pydantic_field(spec)
        fields[fname] = (annotation, field_info)

    # ``create_model``'s overload signature treats every keyword as a
    # candidate for one of its named parameters (``__config__``,
    # ``__validators__``, …) before falling through to the
    # ``**field_definitions`` catch-all. Splatting an arbitrary
    # ``fields`` dict therefore looks ill-typed to pyright even though
    # the runtime contract accepts it (it is the documented pydantic
    # idiom for dynamic model creation). The cast widens the call
    # site to ``Callable[..., type[BaseModel]]`` so the splat checks.
    creator = cast("Callable[..., type[BaseModel]]", create_model)
    return creator(
        target_name,
        __base__=BaseModel,
        __module__=dx_cls.__module__,
        __doc__=dx_cls.__doc__,
        **fields,
    )


def _annotation_with_axioms(spec: FieldSpec) -> type:
    """Reconstruct an ``Annotated[T, ...]`` annotation including axiom metadata.

    Parameters
    ----------
    spec
        A didactic FieldSpec.

    Returns
    -------
    type
        Either the bare annotation, or ``Annotated[T, *axiom_metadata]``
        when the spec carries any ``annotated-types`` constraints in
        its ``extras["annotated_metadata"]`` list.

    Notes
    -----
    didactic stores ``Annotated`` metadata it does not recognise in
    ``spec.extras``; ``annotated-types`` primitives like ``Ge``/``Le``
    are recognised and live on ``spec.axioms`` as their string-form
    Expr equivalents. To round-trip through Pydantic we prefer the
    original metadata where it survived, otherwise we just send the
    bare annotation: Pydantic doesn't speak panproto-Expr predicates.
    """
    metadata = spec.extras.get("annotated_metadata", ())
    if metadata:
        return Annotated[spec.annotation, *metadata]  # type: ignore[valid-type]
    return spec.annotation


def _to_pydantic_field(spec: FieldSpec) -> FieldInfo:
    """Translate one ``FieldSpec`` into a ``pydantic.Field(...)`` call.

    Parameters
    ----------
    spec
        The didactic FieldSpec.

    Returns
    -------
    FieldInfo
        A Pydantic ``FieldInfo`` produced by ``pydantic.Field(...)``.
    """
    # Pydantic's ``Field`` accepts a heterogeneous mix of native types
    # (str, bool, FieldValue defaults, callables, dicts) for its many
    # named keywords. The kwarg dict's value type is therefore the
    # union of all those, expressed as ``FieldValue`` plus
    # ``Callable``/``dict`` and explicitly admitted at each assignment
    # site below.
    type _FieldKwargValue = (
        FieldValue | Callable[[], FieldValue] | dict[str, FieldValue]
    )
    kwargs: dict[str, _FieldKwargValue] = {}

    if spec.default is not MISSING:
        kwargs["default"] = cast("FieldValue", spec.default)
    if spec.default_factory is not None:
        kwargs["default_factory"] = spec.default_factory

    if spec.alias is not None:
        kwargs["alias"] = spec.alias

    if spec.description is not None:
        kwargs["description"] = spec.description
    if spec.examples:
        kwargs["examples"] = list(spec.examples)
    if spec.deprecated:
        kwargs["deprecated"] = True

    # surface anything else through json_schema_extra; this round-trips
    # to from_pydantic via the same key
    extras = {
        k: cast("FieldValue", v)
        for k, v in spec.extras.items()
        if k != "annotated_metadata"
    }
    if extras:
        kwargs["json_schema_extra"] = extras

    # Same dynamic-kwargs pattern as ``create_model``: ``Field``'s
    # overloads enumerate named parameters (``alias``, ``description``,
    # …) and pyright matches each kwarg against the most specific
    # overload first, so a splatted ``dict[str, FieldValue]`` doesn't
    # fit any overload. The cast widens to a permissive shape that
    # matches Pydantic's runtime contract (returns a ``FieldInfo``).
    field_factory = cast("Callable[..., FieldInfo]", Field)
    return field_factory(**kwargs)


__all__ = ["to_pydantic"]
