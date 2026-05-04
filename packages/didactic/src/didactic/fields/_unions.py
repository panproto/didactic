# ``TaggedUnion.model_validate`` overrides the base class with a
# narrower payload type; the runtime accepts the base shape too. The
# ``Literal[...]`` discriminator extraction goes through annotation
# walking that pyright can't follow. Tracked in panproto/didactic#1.
"""Tagged (discriminated) unions over [Model][didactic.api.Model] subclasses.

Pydantic-shaped discriminated unions: declare a base class with a
``discriminator=`` class kwarg, then declare each variant as a subclass
of that base. Each variant must give the discriminator field a
``Literal["..."]`` annotation; the literal's value identifies the variant.

Examples
--------
>>> import didactic.api as dx
>>> from typing import Literal
>>>
>>> class Cadence(dx.TaggedUnion, discriminator="kind"):
...     '''Sum-type base; each variant carries its own fields.'''
>>>
>>> class Perfect(Cadence):
...     kind: Literal["perfect"]
...     strength: float = 1.0
>>>
>>> class Half(Cadence):
...     kind: Literal["half"]
...     strength: float = 0.5
>>>
>>> # dispatch on the discriminator
>>> c = Cadence.model_validate({"kind": "perfect", "strength": 0.9})
>>> isinstance(c, Perfect)
True

Notes
-----
``dx.TaggedUnion`` does not introduce a new metaclass; it leverages
[Model][didactic.api.Model]'s metaclass and adds variant-registration logic
via ``__init_subclass__``. The discriminator field translates as a
``Literal`` in the type-translation layer; the Theory side will emit
the union as a sum-type sort once we round-trip against a real
``panproto.Theory``.

See Also
--------
didactic.models._model.Model : the foundation TaggedUnion sits on.
didactic.models._meta.ModelMeta : the metaclass; unchanged.
"""

from __future__ import annotations

import annotationlib
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast, get_args, get_origin

from didactic.fields._validators import ValidationError, ValidationErrorEntry
from didactic.models._model import Model

if TYPE_CHECKING:
    from collections.abc import Mapping

    from didactic.types._typing import FieldValue, JsonValue, Opaque


class TaggedUnion(Model):
    """Base class for discriminated unions of [Model][didactic.api.Model] subclasses.

    Subclassing forms
    -----------------

    A *union root* declares the discriminator field name::

        class Shape(dx.TaggedUnion, discriminator="kind"): ...

    A *variant* extends the root and pins the discriminator to one
    Literal value, then declares its own fields::

        class Circle(Shape):
            kind: Literal["circle"]
            radius: float


        class Square(Shape):
            kind: Literal["square"]
            side: float

    Dispatch happens at the root: ``Shape.model_validate({"kind": ...})``
    looks up the discriminator value in ``Shape.__variants__`` and
    constructs the corresponding variant.

    Notes
    -----
    Validation and serialisation on a variant work exactly like any
    [Model][didactic.api.Model]; there is no overhead at the variant
    level. Only ``Shape.model_validate`` and ``Shape.model_validate_json``
    do the dispatch.

    See Also
    --------
    didactic.Model : the base class TaggedUnion extends.
    """

    __discriminator__: ClassVar[str | None] = None
    __variants__: ClassVar[dict[FieldValue, type[TaggedUnion]]] = {}

    def __init_subclass__(
        cls,
        *,
        discriminator: str | None = None,
        **kwargs: Opaque,
    ) -> None:
        """Register the class as either a union root or a variant.

        Parameters
        ----------
        discriminator
            The field name used to tag variants. Supplied on the union
            root only::

                class Shape(dx.TaggedUnion, discriminator="kind"): ...
        **kwargs
            Pass-through to [Model][didactic.api.Model]'s metaclass kwargs.

        Raises
        ------
        TypeError
            If a variant cannot resolve the discriminator value from its
            own ``Literal[...]``-annotated discriminator field.
        """
        super().__init_subclass__(**kwargs)
        if discriminator is not None:
            cls.__discriminator__ = discriminator
            # fresh registry per union root
            cls.__variants__ = {}
            return

        # variant: locate the union root in MRO
        root = _find_union_root(cls)
        if root is None or root is cls:
            return

        disc_field = root.__discriminator__
        if disc_field is None:
            return

        # NOTE: we read annotations directly here rather than through the
        # metaclass's `__field_specs__` because `__init_subclass__` fires
        # *during* the metaclass's __new__, before __field_specs__ is set.
        annotations = annotationlib.get_annotations(
            cls,
            format=annotationlib.Format.FORWARDREF,
        )
        if disc_field not in annotations:
            msg = (
                f"variant {cls.__name__} of TaggedUnion {root.__name__} must "
                f"declare a `{disc_field}` field"
            )
            raise TypeError(msg)

        # extract the Literal value(s)
        values = _literal_values(annotations[disc_field])
        if not values:
            msg = (
                f"variant {cls.__name__}.{disc_field} must be annotated as "
                f"Literal[...] with at least one value; got {annotations[disc_field]!r}"
            )
            raise TypeError(msg)

        for value in values:
            if value in root.__variants__:
                existing = root.__variants__[value]
                msg = (
                    f"discriminator value {value!r} is already registered "
                    f"to {existing.__name__}; cannot also register {cls.__name__}"
                )
                raise TypeError(msg)
            root.__variants__[value] = cls

    @classmethod
    def model_validate(cls, payload: Mapping[str, FieldValue | JsonValue]) -> Self:
        """Dispatch on the discriminator and validate as the matched variant.

        Parameters
        ----------
        payload
            Mapping that includes the discriminator field.

        Returns
        -------
        TaggedUnion
            An instance of the matching variant subclass.

        Raises
        ------
        didactic.ValidationError
            If the discriminator field is missing or its value is
            unknown to the union.
        """
        # dispatch only at the union root; i.e. where the discriminator
        # was *set on this class*, not merely inherited. A variant
        # inherits __discriminator__/__variants__ from its parent and
        # must construct itself directly via Model.model_validate.
        is_root = (
            "__discriminator__" in cls.__dict__
            and cls.__dict__["__discriminator__"] is not None
        )
        if not is_root:
            return super().model_validate(payload)

        disc = cls.__discriminator__
        if not isinstance(payload, dict) or disc not in payload:
            entry = ValidationErrorEntry(
                loc=(),
                type="missing_discriminator",
                msg=f"payload is missing the discriminator field {disc!r}",
            )
            raise ValidationError(entries=(entry,), model=cls)

        # ``payload`` is widened to ``Mapping[str, FieldValue | JsonValue]``
        # to match the base ``model_validate`` signature; the discriminator
        # value is recorded in ``__variants__`` under a ``FieldValue`` key.
        value = cast("FieldValue", payload[disc])
        variant = cls.__variants__.get(value)
        if variant is None:
            entry = ValidationErrorEntry(
                loc=(disc,),
                type="unknown_discriminator",
                msg=(
                    f"discriminator value {value!r} is not registered to "
                    f"any variant of {cls.__name__}"
                ),
            )
            raise ValidationError(entries=(entry,), model=cls)

        # ``variant`` is a concrete subclass of ``cls``; the return type
        # is bound to ``Self`` of the union root by design (the dispatch
        # contract is "give me a value of *some* variant").
        return cast("Self", variant.model_validate(payload))


def _find_union_root(cls: type[TaggedUnion]) -> type[TaggedUnion] | None:
    """Walk MRO to find the nearest ancestor with a non-None ``__discriminator__``."""
    for klass in cls.__mro__[1:]:
        if (
            issubclass(klass, TaggedUnion)
            and klass.__dict__.get("__discriminator__") is not None
        ):
            return klass
    return None


def _literal_values(annotation: Opaque) -> tuple[FieldValue, ...]:
    """Extract the values from a ``Literal[...]`` annotation.

    Returns an empty tuple when the annotation isn't a Literal.
    """
    if get_origin(annotation) is Literal:
        return get_args(annotation)
    return ()


__all__ = [
    "TaggedUnion",
]
