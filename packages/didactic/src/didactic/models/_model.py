"""The user-facing ``Model`` base class.

A ``Model`` instance is a typed view onto a
[ModelStorage][didactic.models._storage.ModelStorage]. v0.0.1 ships with a
[DictStorage][didactic.models._storage.DictStorage] backend so the surface
(construction, attribute access, immutable update, serialisation,
equality) can be exercised before the panproto runtime is wired in. The
interface is identical between the two backends; swapping in panproto's
``Schema`` later is a one-file edit.

Notes
-----
Models are immutable. ``with_(...)`` returns a new instance with the
specified fields replaced. There is no in-place mutation; this matches
the panproto schema substrate, where Schemas are immutable values.

See Also
--------
didactic.models._meta : the metaclass that produces field specs.
didactic.fields._fields : the FieldSpec layer.
didactic.models._storage : the pluggable storage backend.
"""

# ``__init__(**kwargs: FieldValue | JsonValue)`` accepts JSON-shape
# dicts but pyright doesn't carry the union through ``_encode_field``.
from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Annotated,
    ClassVar,
    Self,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
)
from uuid import UUID

from didactic.fields._fields import MISSING, Field, MissingType
from didactic.fields._validators import (
    ValidationError,
    ValidationErrorEntry,
)
from didactic.models._meta import ModelMeta, read_class_annotations
from didactic.models._storage import DictStorage

if TYPE_CHECKING:
    from collections.abc import Mapping

    from didactic.axioms._axioms import Axiom
    from didactic.codegen._json_schema import JsonSchemaDoc
    from didactic.fields._fields import FieldSpec
    from didactic.types._typing import Encoded, FieldValue, JsonObject, JsonValue


class Model(metaclass=ModelMeta):
    """Base class for didactic models.

    Subclasses declare fields as ordinary type-annotated class attributes::

        import didactic as dx


        class User(dx.Model):
            id: str
            email: str
            display_name: str = ""

    Construction validates the fields against the class's
    ``__field_specs__``; attribute access decodes from the underlying
    storage on each call (no parallel Python-side mirror).

    Notes
    -----
    Instances are frozen. Use [with_][didactic.api.Model.with_] to produce a
    new instance with one or more fields changed.

    See Also
    --------
    didactic.field : the field descriptor constructor.
    didactic.ValidationError : raised on construction failure.
    """

    # ``_storage`` and ``_derived_cache`` are per-instance slots, set via
    # ``object.__setattr__`` in ``__init__`` (the class is frozen). They
    # are deliberately not declared as class-level annotations so the
    # metaclass's ``@dataclass_transform`` does not surface them as
    # synthesized ``__init__`` parameters in subclass type-checking.
    __slots__ = ("_derived_cache", "_storage")

    # Class-level attributes synthesized by the metaclass at class
    # creation time. Declared here so type checkers see them on every
    # subclass; the metaclass overwrites them with concrete values.
    __field_specs__: ClassVar[dict[str, FieldSpec]] = {}
    __computed_fields__: ClassVar[frozenset[str]] = frozenset()
    __class_axioms__: ClassVar[tuple[Axiom, ...]] = ()

    def __class_getitem__(cls, params: object) -> type[Model]:
        """Auto-parameterise a generic Model on subscript.

        ``Range[int]`` returns a concrete subclass of ``Range`` whose
        ``T``-typed fields use ``int``. The synthesised class is
        cached per ``cls`` and per type-arg tuple, so repeated
        subscripts return the same class object (and that class's
        ``Theory`` is built once).

        Falls back to typing's machinery when ``cls`` declares no
        ``TypeVar`` field annotations to substitute (the subscript
        becomes a structural ``_GenericAlias`` for type checkers
        only, no runtime synthesis).

        Parameters
        ----------
        params
            A type or a tuple of types matching the class's
            ``__parameters__`` arity.

        Returns
        -------
        type
            A synthesised concrete subclass when at least one field
            annotation can be substituted; otherwise the upstream
            ``_GenericAlias``.

        Notes
        -----
        Only bare ``TypeVar`` annotations are substituted. Annotations
        that contain a ``TypeVar`` nested inside a generic shape
        (e.g. ``items: tuple[T, ...]``) stay unsubstituted and
        surface the existing ``TypeVar``-encode error.
        """
        return _parameterise(cls, params)

    def __init__(self, **kwargs: FieldValue | JsonValue) -> None:
        """Construct a Model from keyword arguments.

        Parameters
        ----------
        **kwargs
            One value per declared field. Required fields must be supplied.

        Raises
        ------
        didactic.ValidationError
            If required fields are missing, unknown fields are supplied,
            or a value fails the field's converter / type translation.
        """
        cls = type(self)
        specs = cls.__field_specs__

        encoded: dict[str, Encoded] = {}
        errors: list[ValidationErrorEntry] = []

        # collect known kwargs
        for fname, spec in specs.items():
            if fname in kwargs:
                value = kwargs[fname]
            elif spec.is_required:
                errors.append(
                    ValidationErrorEntry(
                        loc=(fname,),
                        type="missing_required",
                        msg=f"required field {fname!r} not supplied",
                    )
                )
                continue
            else:
                default = spec.make_default()
                # Required fields would have errored above; non-required
                # fields always have a concrete default (or factory).
                if isinstance(default, MissingType):
                    msg = f"non-required field {fname!r} returned MISSING"
                    raise AssertionError(msg)
                value = default

            try:
                encoded_value = _encode_field(spec, cast("FieldValue", value))
            except (TypeError, ValueError) as exc:
                errors.append(
                    ValidationErrorEntry(
                        loc=(fname,),
                        type="type_error",
                        msg=str(exc),
                    )
                )
                continue
            encoded[fname] = encoded_value

        # flag unknown kwargs; but tolerate computed-field names because
        # model_dump round-trips include them, and rejecting them would
        # break model_validate(model_dump(...)) for any model with
        # computed fields.
        computed_names = cls.__computed_fields__
        from didactic.fields._derived import derived_field_names  # noqa: PLC0415

        derived_names = derived_field_names(cls)
        # ``extra="ignore"`` silently drops unknown kwargs at construction.
        # ``with_()`` stays strict regardless: an unknown kwarg there is
        # always a programming error (see ``Model.with_``).
        ignore_extra = cls.__model_config__.extra == "ignore"
        for k in kwargs:
            if k in specs or k in computed_names or k in derived_names:
                continue
            if ignore_extra:
                continue
            errors.append(
                ValidationErrorEntry(
                    loc=(k,),
                    type="extra_field",
                    msg=f"unknown field {k!r}",
                )
            )

        if errors:
            raise ValidationError(entries=tuple(errors), model=cls)

        # bypass our own __setattr__ guard
        object.__setattr__(self, "_storage", DictStorage(encoded))
        object.__setattr__(self, "_derived_cache", {})

        # axiom enforcement: each class-level axiom is parsed via
        # panproto.parse_expr and evaluated against the field environment
        if cls.__class_axioms__:
            from didactic.axioms._axiom_enforcement import (  # noqa: PLC0415
                check_class_axioms,
            )

            env = {fname: getattr(self, fname) for fname in specs}
            failures = check_class_axioms(cls, env)
            if failures:
                axiom_errors = tuple(
                    ValidationErrorEntry(
                        loc=(),
                        type="axiom_failed",
                        msg=msg,
                    )
                    for msg in failures
                )
                raise ValidationError(entries=axiom_errors, model=cls)

    # -- attribute access ---------------------------------------------------

    def __getattr__(self, name: str) -> FieldValue:
        """Decode and return one field from the underlying storage.

        Parameters
        ----------
        name
            The field name.

        Returns
        -------
        FieldValue
            The decoded value.

        Raises
        ------
        AttributeError
            If ``name`` is not a declared field.
        """
        # `__getattr__` is only called for misses on `__getattribute__`,
        # so we never accidentally shadow methods declared on the class.
        cls = type(self)
        try:
            spec = cls.__field_specs__[name]
        except KeyError:
            msg = f"{cls.__name__!r} has no field {name!r}"
            raise AttributeError(msg) from None
        encoded = self._storage.get(name)
        return spec.translation.decode(encoded)

    def __setattr__(self, name: str, value: FieldValue) -> None:
        """Reject all attribute assignment after construction."""
        msg = (
            f"{type(self).__name__} is immutable; use `.with_({name}=...)` to "
            "produce a new instance"
        )
        raise AttributeError(msg)

    # -- immutable update ---------------------------------------------------

    def with_(self, **changes: FieldValue) -> Self:
        """Return a new instance with the specified fields replaced.

        Parameters
        ----------
        **changes
            Field-name -> new-value pairs.

        Returns
        -------
        Model
            A new instance of the same class with the changes applied.

        Raises
        ------
        didactic.ValidationError
            If any change fails type translation or refers to an unknown field.
        """
        cls = type(self)
        specs = cls.__field_specs__
        errors: list[ValidationErrorEntry] = []
        encoded: dict[str, Encoded] = {}

        for k, v in changes.items():
            if k not in specs:
                errors.append(
                    ValidationErrorEntry(
                        loc=(k,),
                        type="extra_field",
                        msg=f"unknown field {k!r}",
                    )
                )
                continue
            try:
                encoded[k] = _encode_field(specs[k], v)
            except (TypeError, ValueError) as exc:
                errors.append(
                    ValidationErrorEntry(loc=(k,), type="type_error", msg=str(exc))
                )

        if errors:
            raise ValidationError(entries=tuple(errors), model=cls)

        new_storage = self._storage.replaced(encoded)
        new = cls.__new__(cls)
        object.__setattr__(new, "_storage", new_storage)
        return new

    # -- serialisation ------------------------------------------------------

    def model_dump(
        self,
        *,
        include: set[str] | None = None,
        exclude: set[str] | None = None,
        by_alias: bool = False,
        exclude_none: bool = False,
        exclude_defaults: bool = False,
    ) -> dict[str, FieldValue]:
        """Render this Model as a plain dict of decoded values.

        Parameters
        ----------
        include
            If set, only emit fields whose name is in this set.
        exclude
            If set, omit fields whose name is in this set. Applied
            after ``include``.
        by_alias
            If ``True``, use each field's
            [alias][didactic.api.field] (where set) as the key in the
            output dict instead of the field name.
        exclude_none
            If ``True``, omit fields whose value is ``None``.
        exclude_defaults
            If ``True``, omit fields whose current value equals
            their declared default.

        Returns
        -------
        dict
            ``{field_name: decoded_value}`` for every selected field
            plus every computed field. Embedded sub-models recurse
            into nested dicts so the result is fully JSON-shaped.

        See Also
        --------
        Model.model_dump_json : JSON-stringified variant.
        """
        cls = type(self)
        result: dict[str, FieldValue] = {}
        for fname, spec in cls.__field_specs__.items():
            if include is not None and fname not in include:
                continue
            if exclude is not None and fname in exclude:
                continue
            value = spec.translation.decode(self._storage.get(fname))
            if exclude_none and value is None:
                continue
            if exclude_defaults and not spec.is_required and value == spec.default:
                continue
            key = spec.alias if by_alias and spec.alias else fname
            # Sum-sort fields must run first: a sum field whose current
            # value is a Model variant would otherwise be dumped as a
            # plain Model below and lose its constructor tag.
            if spec.translation.inner_kind == "sum":
                result[key] = cast(
                    "FieldValue", json.loads(spec.translation.encode(value))
                )
            elif isinstance(value, Model):
                # Embed[T] fields: recurse into the sub-model
                result[key] = value.model_dump(by_alias=by_alias)
            else:
                result[key] = value
        # computed fields evaluate on access; include them in the dump but
        # never include them in storage / construction.
        for cname in cls.__computed_fields__:
            if include is not None and cname not in include:
                continue
            if exclude is not None and cname in exclude:
                continue
            value = getattr(self, cname)
            if exclude_none and value is None:
                continue
            if isinstance(value, Model):
                result[cname] = value.model_dump(by_alias=by_alias)
            else:
                result[cname] = value
        # derived fields are computed once, cached, and dumped alongside
        # regular fields. We import lazily to avoid an import cycle.
        from didactic.fields._derived import derived_field_names  # noqa: PLC0415

        for dname in derived_field_names(cls):
            if include is not None and dname not in include:
                continue
            if exclude is not None and dname in exclude:
                continue
            value = getattr(self, dname)
            if exclude_none and value is None:
                continue
            if isinstance(value, Model):
                result[dname] = value.model_dump(by_alias=by_alias)
            else:
                result[dname] = value
        return result

    def model_dump_json(self, *, indent: int | None = None) -> str:
        """Render this Model as a JSON string.

        Parameters
        ----------
        indent
            JSON indentation level. ``None`` produces compact JSON; an
            integer produces pretty-printed output.

        Returns
        -------
        str
            JSON encoding of [model_dump][didactic.api.Model.model_dump].

        Notes
        -----
        Field values that are not natively JSON-encodable (``datetime``,
        ``Decimal``, ``UUID``, ``bytes``, ``frozenset``) are converted to
        JSON-friendly forms; ``datetime`` to ISO 8601 strings, ``Decimal``
        to numeric strings, ``UUID`` to its canonical string form,
        ``bytes`` to hex, and ``frozenset`` to a sorted list. The same
        conversions are unwound by
        [model_validate_json][didactic.api.Model.model_validate_json].

        See Also
        --------
        Model.model_dump : dict-shaped equivalent.
        Model.model_validate_json : the inverse direction.
        """
        return json.dumps(
            _to_json_safe(self.model_dump()),
            indent=indent,
            sort_keys=False,
            ensure_ascii=False,
        )

    @classmethod
    def model_json_schema(cls) -> JsonSchemaDoc:
        """Build a JSON Schema (Draft 2020-12) document for this Model.

        Returns
        -------
        dict
            A JSON Schema object describing the Model's fields,
            required keys, and any ``annotated-types`` constraints
            (``Ge``/``Le``/``MinLen``/etc.). Pydantic-shaped consumers
            (FastAPI, OpenAPI generators) can use this directly.

        See Also
        --------
        didactic.codegen.json_schema_of : the underlying implementation.
        """
        from didactic.codegen._json_schema import json_schema_of  # noqa: PLC0415

        return json_schema_of(cls)

    @classmethod
    def emit_as(cls, target: str, **opts: object) -> bytes:  # noqa: ARG003
        """Emit this Model class under the named ``target`` format.

        Parameters
        ----------
        target
            Either a custom-emitter target name (registered via
            ``@dx.codegen.emitter`` or
            ``dx.codegen.register_emitter``), a panproto IoRegistry
            protocol (``"avro"``, ``"openapi"``, ...), or a panproto
            grammar name (``"rust"``, ``"typescript"``, ...).
        **opts
            Optional emitter-specific options.

        Returns
        -------
        bytes
            The emitted artefact.

        Raises
        ------
        LookupError
            If no emitter, codec, or grammar matches ``target``.

        Notes
        -----
        Lookup order: custom emitters first, then ``IoRegistry``
        protocols, then ``AstParserRegistry`` grammars. The
        ``"json_schema"`` target is handled specially: it uses
        didactic's own JSON Schema generator rather than panproto's
        codec, so the output matches Pydantic's dialect.
        """
        # special-case json_schema; we own the dialect
        if target == "json_schema":
            import json  # noqa: PLC0415

            return json.dumps(cls.model_json_schema(), indent=2).encode("utf-8")

        from didactic.codegen._emitter import lookup_emitter  # noqa: PLC0415

        # custom emitters
        custom = lookup_emitter(target)
        if custom is not None:
            try:
                return custom.emit_class(cls)
            except NotImplementedError:
                pass

        from didactic.codegen import io as io_module  # noqa: PLC0415
        from didactic.codegen import source as source_module  # noqa: PLC0415

        # IoRegistry protocols
        if target in io_module.list_protocols():
            # for protocols, the schema artefact is what we emit; the
            # "instance" we pass is a sentinel built from the class
            # itself (used by panproto codecs that emit schemas
            # directly from a Schema object)
            import panproto  # noqa: PLC0415

            from didactic.vcs._repo import schema_from_model  # noqa: PLC0415

            registry = panproto.IoRegistry()
            schema = schema_from_model(cls)
            instance = panproto.Instance.from_json(schema, cls.__name__, "{}")
            return registry.emit(target, schema, instance)

        # AstParserRegistry grammars (de-novo emission)
        if target in source_module.available_targets():
            return source_module.emit_pretty(cls, target=target)

        msg = (
            f"emit_as({target!r}): no registered emitter, IoRegistry codec, "
            f"or grammar matches that target. Use "
            f"dx.codegen.list_emitters() / dx.codegen.io.list_protocols() / "
            f"dx.codegen.source.available_targets() to enumerate."
        )
        raise LookupError(msg)

    @classmethod
    def model_validate(cls, payload: Mapping[str, FieldValue | JsonValue]) -> Self:
        """Construct a Model from a dict payload.

        Parameters
        ----------
        payload
            ``{field_name: value}`` mapping. Equivalent to ``cls(**payload)``.

        Returns
        -------
        Model
            The validated instance.

        Raises
        ------
        didactic.ValidationError
            If validation fails.

        See Also
        --------
        Model.model_validate_json : variant that takes a JSON string.
        """
        return cls(**payload)

    @classmethod
    def model_validate_json(cls, raw: str | bytes | bytearray) -> Self:
        """Construct a Model from a JSON string.

        Parameters
        ----------
        raw
            JSON-encoded payload; string, bytes, or bytearray.

        Returns
        -------
        Model
            The validated instance.

        Raises
        ------
        didactic.ValidationError
            If validation fails.
        json.JSONDecodeError
            If ``raw`` is not valid JSON.

        Notes
        -----
        After JSON decode, values are converted back through each field's
        decoder pipeline; any JSON-vs-Python representation gap (e.g.
        ``datetime`` from ISO string, ``Decimal`` from numeric string) is
        bridged before the call into the type translation layer.
        """
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        payload: object = json.loads(raw)
        if not isinstance(payload, dict):
            entry = ValidationErrorEntry(
                loc=(),
                type="type_error",
                msg=f"expected JSON object, got {type(payload).__name__}",
            )
            raise ValidationError(entries=(entry,), model=cls)
        # ``json.loads`` returns ``Any``; the isinstance narrows the
        # outer shape but pyright still treats the keys/values as unknown.
        # ``cast`` declares what we actually parsed (a JSON object).
        typed_payload = cast("JsonObject", payload)
        return cls.model_validate(_from_json_payload(cls, typed_payload))

    # -- dunder ---------------------------------------------------------

    def __eq__(self, other: Self | FieldValue) -> bool:  # type: ignore[override]
        """Two Models are equal iff their class matches and storages compare equal."""
        if type(other) is not type(self):
            return NotImplemented
        return self._storage == other._storage  # type: ignore[attr-defined]

    def __hash__(self) -> int:
        """Hash from the underlying storage's canonical form."""
        return hash((type(self), self._storage))

    def __repr__(self) -> str:
        """Pydantic-style ``ClassName(field=value, ...)`` repr."""
        cls = type(self)
        parts = ", ".join(
            f"{fname}={spec.translation.decode(self._storage.get(fname))!r}"
            for fname, spec in cls.__field_specs__.items()
        )
        return f"{cls.__name__}({parts})"

    # -- low-level storage hook -------------------------------------------

    @classmethod
    def from_storage_dict(cls, items: dict[str, str]) -> Self:
        """Build an instance directly from an encoded-storage dict.

        Parameters
        ----------
        items
            ``{field_name: encoded_value}`` mapping. Values must already
            be in panproto-shape encoded form (the same shape produced
            by [to_storage_dict][didactic.api.Model.to_storage_dict]).

        Returns
        -------
        Model
            A new instance whose storage is built from ``items`` directly,
            **without re-running validation**.

        Notes
        -----
        Private API. Used by [Embed][didactic.api.Embed] field handling and
        by pickle's ``__setstate__`` hook. Bypassing
        validation is safe because the values originated from a previously
        validated instance; do not feed user-supplied data through this
        hook.
        """
        new = cls.__new__(cls)
        object.__setattr__(new, "_storage", DictStorage(items))
        return new

    def to_storage_dict(self) -> dict[str, str]:
        """Return the encoded-storage dict for this instance.

        Returns
        -------
        dict
            ``{field_name: encoded_value}``; the panproto-shape encoded
            form of every declared field. Round-trips through
            [from_storage_dict][didactic.api.Model.from_storage_dict].
        """
        return cast("DictStorage", self._storage).to_dict()

    # -- pickle ---------------------------------------------------------

    def __getstate__(self) -> dict[str, str]:
        """Pickle hook; return the storage's encoded items.

        Returns
        -------
        dict
            ``{field_name: encoded_value}`` ready to be restored by
            [__setstate__][didactic.api.Model.__setstate__].
        """
        return cast("DictStorage", self._storage).to_dict()

    def __setstate__(self, state: dict[str, str]) -> None:
        """Pickle hook; restore the storage from the encoded items.

        Parameters
        ----------
        state
            The dict produced by [__getstate__][didactic.api.Model.__getstate__].

        Notes
        -----
        Goes through ``object.__setattr__`` because the class's own
        ``__setattr__`` rejects all attribute writes after construction.
        """
        object.__setattr__(self, "_storage", DictStorage(state))
        object.__setattr__(self, "_derived_cache", {})


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _parameterise(cls: type[Model], params: object) -> type[Model]:
    """Synthesise (or fetch from cache) a concrete subclass of a generic ``cls``.

    Implementation of ``Model.__class_getitem__``; lifted to a
    module-level function so the static-type narrowing of ``params``
    isn't trapped behind a class scope's restricted self/cls vocabulary.
    """
    params_tuple: tuple[object, ...] = (
        cast("tuple[object, ...]", params) if isinstance(params, tuple) else (params,)
    )

    typevars: tuple[TypeVar, ...] = cast(
        "tuple[TypeVar, ...]", getattr(cls, "__parameters__", ())
    )
    if not typevars or len(typevars) != len(params_tuple):
        return _fallback_subscript(cls, params_tuple)

    cache: dict[tuple[object, ...], type[Model]] | None = cls.__dict__.get(
        "__parameterised_cache__"
    )
    if cache is None:
        cache = {}
        # ``setattr`` rather than direct assignment so the metaclass's
        # frozen-class guard doesn't fire on this private bookkeeping
        # attribute (it's not in ``__field_specs__``).
        cls.__parameterised_cache__ = cache  # type: ignore[attr-defined]
    cached = cache.get(params_tuple)
    if cached is not None:
        return cached

    substitution: dict[TypeVar, object] = dict(zip(typevars, params_tuple, strict=True))
    base_anns = read_class_annotations(cls)
    new_anns: dict[str, object] = {}
    for fname, ann in base_anns.items():
        substituted = _substitute_typevars(ann, substitution)
        if substituted is not ann:
            new_anns[fname] = substituted
    if not new_anns:
        return _fallback_subscript(cls, params_tuple)

    arg_names = ", ".join(getattr(p, "__name__", str(p)) for p in params_tuple)
    new_name = f"{cls.__name__}[{arg_names}]"
    namespace: dict[str, object] = {
        "__annotations__": new_anns,
        "__module__": cls.__module__,
        "__qualname__": new_name,
    }
    # Propagate every parent FieldSpec's default and metadata onto the
    # synthesised class so the metaclass's MRO walk sees them as
    # own-class defaults. Without this stamp, the substituted-annotation
    # re-build sees raw_default=MISSING for the synth class and treats
    # the field as required.
    parent_specs: dict[str, FieldSpec] = getattr(cls, "__field_specs__", {})
    for fname in new_anns:
        spec = parent_specs.get(fname)
        if spec is None:
            continue
        descriptor = _field_descriptor_from_spec(spec)
        # MISSING is the sentinel meaning "no default and no metadata
        # to propagate"; the field stays required on the synthesised
        # class. Any other value (including ``None``) IS the default.
        if descriptor is not MISSING:
            namespace[fname] = descriptor
    new_cls = cast("type[Model]", type(new_name, (cls,), namespace))
    cache[params_tuple] = new_cls
    return new_cls


def _substitute_typevars(
    annotation: object, substitution: dict[TypeVar, object]
) -> object:
    """Substitute ``TypeVar`` leaves in ``annotation`` against ``substitution``.

    Walks through nested generic shapes and returns a new annotation
    with every ``TypeVar`` replaced by its concrete type. Returns the
    original ``annotation`` object when no substitution applies, so
    callers can use identity comparison to detect changes.

    Handled shapes:

    - bare ``TypeVar`` -> the substitution target.
    - parameterised generic (``list[T]``, ``tuple[T, U]``,
      ``tuple[T, ...]``, ``dict[str, T]``, ``frozenset[T]``,
      ``Embed[T]``, ``Ref[T]``, ``Annotated[T, ...]``, etc.) -> the
      origin re-subscripted with substituted args.
    - union (``T | int``, ``Union[T, str]``) -> a new union with each
      arm substituted.
    - non-generic types and ``ForwardRef`` -> returned as-is.

    Recursion bottoms out at non-substitutable leaves (real types,
    forward references, primitive literals).
    """
    # bare TypeVar leaf
    if isinstance(annotation, TypeVar):
        return substitution.get(annotation, annotation)

    args = get_args(annotation)
    if not args:
        return annotation

    new_args = tuple(_substitute_typevars(a, substitution) for a in args)
    if new_args == args:
        return annotation

    origin = get_origin(annotation)
    # PEP 604 / typing union: rebuild via ``typing.Union[(...)]`` which
    # accepts a tuple of arms and produces the appropriate union form.
    # Ruff prefers ``X | Y``, but that can't be expressed for a runtime
    # tuple of arms; ``noqa: UP007`` keeps the dynamic form.
    if origin in {Union, UnionType}:
        return Union[new_args]  # noqa: UP007
    # ``Annotated[T, *meta]`` keeps its metadata tuple. Pyright's
    # static check on ``Annotated[<dynamic-tuple>]`` requires the args
    # to be statically known. Route through ``typing._SpecialForm``'s
    # subscript via the standard ``[...]`` syntax wrapped in ``cast``
    # to a plain subscriptable; the runtime construction works because
    # ``obj[a, b, c]`` is sugar for ``obj.__getitem__((a, b, c))``.
    if origin is Annotated:
        meta = args[1:]
        new_base = new_args[0]
        if new_base is args[0]:
            return annotation
        # ``Annotated`` is a ``typing._SpecialForm`` whose ``__getitem__``
        # accepts a tuple ``(base, *meta)``. The subscript syntax compiles
        # to that call exactly; pyright doesn't model the special form, so
        # cast to a subscriptable proxy.
        annotated_subscript: object = Annotated
        return cast("object", annotated_subscript[(new_base, *meta)])  # type: ignore[index]
    # Generic alias: re-subscript the origin with the new args.
    # ``tuple[T, ...]`` keeps the Ellipsis sentinel verbatim because
    # ``Ellipsis`` is not a TypeVar (substitution returns it unchanged).
    if origin is None:
        return annotation
    if not new_args:
        return annotation
    try:
        return origin[new_args[0]] if len(new_args) == 1 else origin[new_args]
    except TypeError:
        return annotation


def _field_descriptor_from_spec(spec: FieldSpec) -> object:
    """Reconstruct a ``Field`` descriptor (or bare default) from a ``FieldSpec``.

    Used by ``_parameterise`` to propagate a generic-parent's defaults
    and metadata onto the synthesised concrete subclass. Returns the
    sentinel ``MISSING`` when the parent spec carried neither a
    default nor any metadata that needs to round-trip through
    ``Field``: in that case the field stays required on the
    synthesised class, matching the parent's behaviour. Otherwise
    returns either the bare default value (for plain ``f: T = 0``)
    or a fully-populated ``Field`` descriptor (for any spec carrying
    metadata beyond a default).
    """
    has_default = spec.default is not MISSING
    has_factory = spec.default_factory is not None
    has_metadata = bool(
        spec.alias
        or spec.description
        or spec.examples
        or spec.deprecated
        or spec.nominal
        or spec.converter
        or spec.usage_mode != "readwrite"
        or spec.extras
    )
    if not (has_default or has_factory or has_metadata):
        return MISSING
    if has_default and not has_metadata and not has_factory:
        return spec.default
    return Field(
        default=spec.default,
        default_factory=spec.default_factory,
        converter=spec.converter,
        alias=spec.alias,
        description=spec.description,
        examples=spec.examples,
        deprecated=spec.deprecated,
        nominal=spec.nominal,
        usage_mode=spec.usage_mode,
        extras=dict(spec.extras) if spec.extras else None,
    )


def _fallback_subscript(cls: type[Model], params: object) -> type[Model]:
    """Defer a non-synthesisable ``cls[params]`` to typing's machinery.

    When ``cls`` declares no ``Generic[...]`` parameters, or when
    ``params`` doesn't substitute any of its TypeVar field
    annotations, the subscript falls through here. ``Generic`` (if
    present in the MRO) returns a ``_GenericAlias`` for the static
    type checker; otherwise typing raises ``TypeError``.
    """
    # Walk the MRO past ``Model`` itself to find an ancestor's
    # ``__class_getitem__`` (typically ``Generic.__class_getitem__``
    # when the user wrote ``class Foo(dx.Model, Generic[T]): ...``).
    # If no ancestor defines it, raise the same error typing would
    # have raised for a non-generic class.
    for base in cls.__mro__:
        if base is Model:
            continue
        descriptor = base.__dict__.get("__class_getitem__")
        if descriptor is None:
            continue
        # The descriptor is a classmethod (Generic), classmethod_descriptor
        # (object), or function. ``__get__(None, cls)`` rebinds it to
        # ``cls`` so the call invokes ``base.__class_getitem__(cls, params)``
        # with ``cls`` as the receiver, matching the lookup ``cls[params]``
        # would have produced if ``Model`` were not in the MRO.
        rebound = descriptor.__get__(None, cls)
        return cast("type[Model]", rebound(params))
    msg = (
        f"{cls.__name__!r} does not declare any ``Generic[...]`` "
        "type parameters; subscripting is not supported."
    )
    raise TypeError(msg)


def _to_json_safe(value: FieldValue | JsonValue) -> JsonValue:
    """Recursively coerce a decoded value into a JSON-encodable form.

    Parameters
    ----------
    value
        A value produced by a field decoder.

    Returns
    -------
    JsonValue
        A JSON-safe value: ``str``, ``int``, ``float``, ``bool``, ``None``,
        ``list``, or ``dict``.

    Notes
    -----
    Conversions:
    ``datetime``/``date``/``time`` -> ISO 8601 string.
    ``Decimal`` -> numeric string (preserves precision).
    ``UUID`` -> canonical string form.
    ``bytes`` -> hex string.
    ``tuple``/``frozenset`` -> list (sorted for ``frozenset``).
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Model):
        # embedded sub-model; recurse into its model_dump shape
        return _to_json_safe(value.model_dump())
    if isinstance(value, dict):
        return {k: _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_safe(v) for v in value]
    # All remaining FieldValue / JsonValue inhabitants are frozensets
    # after the preceding ``isinstance`` cascade.
    # sort by repr so output is deterministic across runs
    return sorted((_to_json_safe(v) for v in value), key=repr)


def _from_json_payload(
    cls: ModelMeta, payload: JsonObject
) -> dict[str, FieldValue | JsonValue]:
    """Reverse the JSON-friendly conversions applied by :func:`_to_json_safe`.

    Each known field's JSON-decoded value is routed through the field's
    ``translation.from_json`` callable, which knows how to produce the
    Python-native value the encoder expects.

    Parameters
    ----------
    cls
        The Model class being validated.
    payload
        The dict produced by ``json.loads``.

    Returns
    -------
    dict
        A new dict with values coerced into Python-native forms ready for
        the field-encoder pipeline.
    """
    out: dict[str, FieldValue | JsonValue] = {}
    for fname, raw in payload.items():
        spec = cls.__field_specs__.get(fname)
        if spec is None:
            # unknown fields fall through; the Model __init__ will reject them
            out[fname] = raw
            continue
        out[fname] = spec.translation.from_json(raw)
    return out


def _encode_field(spec: FieldSpec, value: FieldValue) -> Encoded:
    """Run the converter (if any) and the type-translation encoder.

    Parameters
    ----------
    spec
        The field's spec.
    value
        The user-supplied value.

    Returns
    -------
    str
        The panproto-shaped encoded form.

    Raises
    ------
    TypeError or ValueError
        If the value cannot be encoded.
    """
    if spec.converter is not None:
        value = spec.converter(value)
    return spec.translation.encode(value)


# alias for adoption ergonomics
BaseModel = Model

__all__ = [
    "BaseModel",
    "Model",
]
