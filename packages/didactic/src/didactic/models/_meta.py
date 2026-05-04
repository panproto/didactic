# The metaclass passes resolved annotations (``type | TypeVar |
# ForwardRef``) into ``classify`` and ``_build_field_spec``, which
# expect the narrower ``TypeForm`` (``type | UnionType``). The
# runtime contract handles the wider input (the metaclass also
# accepts string forward refs and TypeVar instances), but pyright
# can't follow the case split through the dataclass_transform
# layer. Tracked in panproto/didactic#1.
"""The ``ModelMeta`` metaclass: class-as-Theory derivation.

``ModelMeta`` runs at class-creation time. It reads each annotated field,
classifies its type, extracts ``Annotated[...]`` metadata, and produces a
[FieldSpec][didactic.api.FieldSpec] per field. The specs are cached on the
class as ``__field_specs__``.

The Theory-derivation step (constraints, edges, axioms, colimits) is
isolated to [didactic.theory._theory][] so the storage backend can swap from
the dict-backed stand-in to a panproto.Schema-backed one without
touching the rest of the codebase.

Notes
-----
The metaclass uses the ``@dataclass_transform`` decorator (PEP 681) to
tell type checkers that derived classes synthesise an ``__init__``
accepting each annotated field. Flags applied:
``eq_default=True``, ``order_default=False``, ``kw_only_default=False``,
``frozen_default=True``, ``field_specifiers=(Field, field)``.
"""

from __future__ import annotations

# annotationlib is the 3.14+ home for safe annotation reading
import annotationlib
import contextlib
import sys
from typing import TYPE_CHECKING, ForwardRef, TypeVar, cast, dataclass_transform

from didactic.axioms._axioms import collect_class_axioms
from didactic.fields._computed import computed_field_names
from didactic.fields._fields import (
    MISSING,
    Field,
    FieldSpec,
    field,
    read_annotated_metadata,
)
from didactic.models._config import DEFAULT_CONFIG, ExtraPolicy, ModelConfig
from didactic.types._types import TypeForm, classify

if TYPE_CHECKING:
    from collections.abc import Mapping

    import panproto

    from didactic.axioms._axioms import Axiom
    from didactic.types._typing import (
        DefaultOrMissing,
        FieldValue,
        JsonValue,
        Opaque,
    )


def _deferred_encode(_: FieldValue) -> str:
    """Refuse to encode TypeVar-annotated fields on a non-parameterised generic.

    Generic Models cannot be instantiated until subclassed with concrete
    types. Hitting this encoder means the user tried to construct the
    abstract base directly; we surface the limitation as a TypeError.
    """
    msg = (
        "cannot encode a TypeVar-annotated field; the class is generic "
        "and must be parameterised (subclass with concrete types) before "
        "construction"
    )
    raise TypeError(msg)


def _deferred_decode(_: str) -> FieldValue:
    """Refuse to decode TypeVar-annotated fields on a non-parameterised generic.

    Counterpart to [_deferred_encode][didactic.models._meta._deferred_encode].
    """
    msg = (
        "cannot decode a TypeVar-annotated field; the class is generic "
        "and must be parameterised before any value can round-trip"
    )
    raise TypeError(msg)


def _deferred_from_json(_: JsonValue) -> FieldValue:
    """Refuse to coerce JSON values on TypeVar-annotated generic fields.

    Counterpart to [_deferred_decode][didactic.models._meta._deferred_decode]
    with the ``(JsonValue) -> FieldValue`` signature ``TypeTranslation.from_json``
    expects.
    """
    msg = (
        "cannot coerce a TypeVar-annotated field from JSON; the class is "
        "generic and must be parameterised before any value can round-trip"
    )
    raise TypeError(msg)


def _read_class_annotations(cls: type) -> dict[str, type | ForwardRef]:
    """Read a class's annotations through ``annotationlib``, robustly.

    Parameters
    ----------
    cls
        The class whose annotations to read.

    Returns
    -------
    dict
        Mapping of attribute name to resolved annotation. Forward
        references resolve to ``ForwardRef`` proxies rather than raising
        ``NameError``; the caller resolves them lazily.

    Notes
    -----
    The strategy is two-pass to handle both modern PEP 649 annotations
    and legacy modules that still use ``from __future__ import annotations``
    (which stores annotations as raw strings, bypassing ``__annotate__``):

    1. Call ``annotationlib.get_annotations(cls, format=FORWARDREF)``.
       For PEP 649 deferred annotations this returns evaluated types.
    2. Any entries that come back as ``str`` (legacy stringified
       annotations) are evaluated against the class's module globals. On
       NameError we wrap in ``ForwardRef`` so mutual-recursive references
       can be closed later.

    didactic never reads ``cls.__annotations__`` directly.
    """
    raw = annotationlib.get_annotations(
        cls,
        format=annotationlib.Format.FORWARDREF,
    )

    # If everything is already evaluated, we're done.
    if not any(isinstance(v, str) for v in raw.values()):
        return raw

    # Legacy stringified annotations: resolve against the module globals
    # plus a localns that includes the class itself (for self-reference).
    module = sys.modules.get(cls.__module__)
    globalns: dict[str, Opaque] = getattr(module, "__dict__", {}) or {}
    localns: dict[str, Opaque] = dict(vars(cls))
    localns.setdefault(cls.__name__, cls)

    resolved: dict[str, type | ForwardRef] = {}
    for name, ann in raw.items():
        if isinstance(ann, str):
            try:
                resolved[name] = eval(ann, globalns, localns)
            except NameError:
                resolved[name] = ForwardRef(ann)
        else:
            resolved[name] = ann
    return resolved


def _build_field_spec(
    name: str,
    annotation: type | TypeVar | ForwardRef,
    raw_default: DefaultOrMissing | Field,
) -> FieldSpec:
    """Resolve one annotation into a FieldSpec.

    Parameters
    ----------
    name
        The Python attribute name.
    annotation
        The (resolved) type annotation.
    raw_default
        Either a [Field][didactic.api.Field] descriptor, ``MISSING``, or a
        plain default value.

    Returns
    -------
    FieldSpec
        The resolved field record.

    Raises
    ------
    didactic.types._types.TypeNotSupportedError
        If the annotation is not (yet) translatable.
    """
    # generic-parameter annotations (TypeVar instances introduced by
    # PEP 695 ``class Foo[T]:`` syntax) are deferred. The class is
    # "abstract" until a concrete subclass binds them. We record the
    # name on __field_specs__ but produce no translation yet; the field
    # cannot be set or read until the class is parameterised.
    # generic-parameter annotations land as either a TypeVar instance
    # (when annotations are evaluated at class-creation time) or as a
    # ForwardRef wrapping the type-variable's name (when
    # ``from __future__ import annotations`` defers evaluation). Both
    # paths produce a deferred FieldSpec.
    tv_name: str | None = None
    if isinstance(annotation, TypeVar):
        tv_name = annotation.__name__
    elif (
        isinstance(annotation, ForwardRef)
        and len(annotation.__forward_arg__) == 1
        and annotation.__forward_arg__.isidentifier()
        and annotation.__forward_arg__.isupper()
    ):
        tv_name = annotation.__forward_arg__
    if tv_name is not None:
        from didactic.types._types import TypeTranslation  # noqa: PLC0415

        deferred = TypeTranslation(
            sort=f"_TypeVar:{tv_name}",
            encode=_deferred_encode,
            decode=_deferred_decode,
            inner_kind="generic",
            from_json=_deferred_from_json,
        )
        return FieldSpec(
            name=name,
            annotation=annotation,
            translation=deferred,
            default=raw_default if not isinstance(raw_default, Field) else MISSING,
            usage_mode="readwrite",
        )
    # Above branches return for ``TypeVar`` / ``ForwardRef`` cases; the
    # remaining annotation is a real ``TypeForm`` (a class, ``UnionType``,
    # ``TypeAliasType``, ``GenericAlias``, or an ``Annotated`` form). Cast
    # to drop the residual ``TypeVar | ForwardRef`` arms from pyright's
    # view.
    type_form = cast("TypeForm", annotation)
    translation = classify(type_form)
    annotated_meta = read_annotated_metadata(type_form)

    # default & metadata sourced from a Field instance, if present
    if isinstance(raw_default, Field):
        f = raw_default
        if f.constraint is not None and annotated_meta.axioms:
            # gentle warning would go here once we wire up logging;
            # for v0.0.1, the union behaviour is to combine both sources
            pass

        return FieldSpec(
            name=name,
            annotation=annotation,
            translation=translation,
            default=f.default,
            default_factory=f.default_factory,
            converter=f.converter,
            alias=f.alias,
            description=f.description or annotated_meta.description,
            examples=f.examples,
            deprecated=f.deprecated,
            nominal=f.nominal,
            usage_mode=f.usage_mode,
            axioms=annotated_meta.axioms,
            extras=dict(annotated_meta.extras) | (dict(f.extras) if f.extras else {}),
        )

    # plain default (possibly MISSING)
    return FieldSpec(
        name=name,
        annotation=annotation,
        translation=translation,
        default=raw_default,
        description=annotated_meta.description,
        axioms=annotated_meta.axioms,
        extras=dict(annotated_meta.extras),
    )


@dataclass_transform(
    eq_default=True,
    order_default=False,
    kw_only_default=False,
    frozen_default=True,
    field_specifiers=(Field, field),
)
class ModelMeta(type):
    """Metaclass for [Model][didactic.api.Model].

    Walks the class body's annotations + defaults at class-creation time
    and produces a per-class ``__field_specs__`` mapping. The full
    Theory-derivation pipeline (constraints, edges, axioms, colimits)
    drops in here in subsequent phases.

    Notes
    -----
    Subclasses inherit field specs through MRO walk in
    [collect_field_specs][didactic.models._meta.ModelMeta.collect_field_specs];
    explicit shadowing in a derived class replaces the inherited spec.

    See Also
    --------
    didactic.Model : the user-facing base class produced by this metaclass.
    """

    # populated on each subclass; read-only at runtime
    __field_specs__: dict[str, FieldSpec]
    __schema_kind__: str
    __model_config__: ModelConfig
    __computed_fields__: tuple[str, ...]
    __class_axioms__: tuple[Axiom, ...]
    __theory_cache__: panproto.Theory | None

    @property
    def __theory__(cls) -> panproto.Theory:
        """The lazily-built ``panproto.Theory`` for this Model class.

        Returns
        -------
        panproto.Theory
            Materialised on first access by
            [build_theory][didactic.theory._theory.build_theory]; cached
            thereafter. Subsequent accesses return the same object.
        """
        cached = cls.__dict__.get("__theory_cache__")
        if cached is None:
            from didactic.theory._theory import build_theory  # noqa: PLC0415

            cached = build_theory(cls)
            cls.__theory_cache__ = cached
        return cached

    # config keys we accept on the class header.
    # e.g. ``class Foo(dx.Model, extra="forbid"): ...``
    _CONFIG_HEADER_KEYS: frozenset[str] = frozenset(
        {"extra", "strict", "populate_by_name", "title", "description"}
    )

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Opaque],
        /,
        **kwargs: Opaque,
    ) -> ModelMeta:
        """Create the class and populate didactic-side metadata."""
        # split kwargs into config-overrides and pass-throughs
        config_overrides = {
            k: kwargs.pop(k) for k in list(kwargs) if k in mcs._CONFIG_HEADER_KEYS
        }
        cls = super().__new__(mcs, name, bases, namespace, **kwargs)

        # the very first pass over `Model` itself has nothing to extract
        if not bases or all(not isinstance(b, ModelMeta) for b in bases):
            cls.__field_specs__ = {}
            cls.__schema_kind__ = name
            cls.__model_config__ = DEFAULT_CONFIG
            cls.__computed_fields__ = ()
            cls.__class_axioms__ = ()
            return cls

        cls.__schema_kind__ = name
        cls.__model_config__ = mcs._resolve_config(cls, config_overrides)
        cls.__field_specs__ = ModelMeta.collect_field_specs(cls)
        cls.__computed_fields__ = computed_field_names(cls)
        cls.__class_axioms__ = collect_class_axioms(cls)
        # placeholder for the cached panproto.Theory; populated lazily
        # by the `__theory__` property the metaclass exposes below.
        cls.__theory_cache__ = None

        # Strip field defaults from the class dict. Class attributes
        # shadow ``__getattr__`` during normal lookup, so leaving the
        # defaults in place would cause ``instance.field_name`` to return
        # the class-level default rather than the per-instance value.
        # AttributeError on delattr means the default lives on a base
        # class; our metaclass will already have stripped it when the
        # base was processed, so suppression is safe.
        for fname in cls.__field_specs__:
            if fname in cls.__dict__ and not callable(cls.__dict__[fname]):
                with contextlib.suppress(AttributeError):
                    delattr(cls, fname)

        return cls

    @staticmethod
    def _resolve_config(
        target: type, header_overrides: Mapping[str, Opaque]
    ) -> ModelConfig:
        """Pick the ModelConfig for a class.

        Parameters
        ----------
        target
            The class being created.
        header_overrides
            Keyword arguments from ``class Foo(dx.Model, extra="forbid")``-style
            class headers, scoped to known config keys.

        Returns
        -------
        ModelConfig
            The merged config. Header overrides take precedence over an
            explicit ``__model_config__`` attribute, which in turn takes
            precedence over inherited / default config.

        Raises
        ------
        TypeError
            If ``__model_config__`` is set but is not a
            [ModelConfig][didactic.api.ModelConfig].
        """
        explicit = target.__dict__.get("__model_config__")
        if explicit is None:
            # walk bases for an inherited config
            for base in target.__mro__[1:]:
                explicit = getattr(base, "__model_config__", None)
                if explicit is not None and explicit is not DEFAULT_CONFIG:
                    break
            if explicit is None:
                explicit = DEFAULT_CONFIG

        if not isinstance(explicit, ModelConfig):
            msg = (
                f"{target.__name__}.__model_config__ must be a ModelConfig "
                f"instance, got {type(explicit).__name__}"
            )
            raise TypeError(msg)

        if not header_overrides:
            return explicit

        # apply overrides via dataclasses.replace-shaped construction. The
        # ``header_overrides`` mapping is keyed on a known small set
        # (``_CONFIG_HEADER_KEYS``); each value is taken at face value and
        # validated by ``ModelConfig.__post_init__`` rather than statically.
        def _pick(key: str, fallback: Opaque) -> Opaque:
            return header_overrides.get(key, fallback)

        return ModelConfig(
            extra=cast("ExtraPolicy", _pick("extra", explicit.extra)),
            strict=cast("bool", _pick("strict", explicit.strict)),
            populate_by_name=cast(
                "bool", _pick("populate_by_name", explicit.populate_by_name)
            ),
            title=cast("str | None", _pick("title", explicit.title)),
            description=cast("str | None", _pick("description", explicit.description)),
        )

    @staticmethod
    def collect_field_specs(target: type) -> dict[str, FieldSpec]:
        """Walk MRO and produce the FieldSpec mapping for ``target``.

        Parameters
        ----------
        target
            The class to inspect.

        Returns
        -------
        dict
            Ordered mapping of field name to [FieldSpec][didactic.api.FieldSpec].
            Iteration order is "base classes first, then derived; within a
            class, definition order from the annotation table".

        Notes
        -----
        Implemented as ``@staticmethod`` rather than ``@classmethod`` because
        the metaclass itself is not used; we walk ``target.__mro__`` directly.
        The first argument is named ``target`` to avoid the ``cls``/``mcs``
        ambiguity that would arise on a classmethod of a metaclass.
        """
        seen: dict[str, FieldSpec] = {}

        # walk MRO in reverse so derived classes overwrite base entries
        for klass in reversed(target.__mro__):
            if not isinstance(klass, ModelMeta):
                continue
            anns = _read_class_annotations(klass)
            for fname, ann in anns.items():
                # skip private / dunder attributes
                if fname.startswith("_"):
                    continue
                raw_default = klass.__dict__.get(fname, MISSING)
                seen[fname] = _build_field_spec(fname, ann, raw_default)

        return seen


__all__ = [
    "ModelMeta",
]
