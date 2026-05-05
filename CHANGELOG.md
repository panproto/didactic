# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-05-05

### Added

- ``pathlib.Path`` (and any ``PurePath`` subclass: ``PurePosixPath``,
  ``PureWindowsPath``, etc.) is a first-class scalar field type. Wire
  format is ``str(path)``; decoding restores the same ``PurePath``
  subclass. ([#21])
- ``enum.StrEnum`` and ``enum.IntEnum`` are first-class scalar field
  types. String-valued and int-valued plain ``enum.Enum`` subclasses
  also work; mixed-value enums raise ``TypeNotSupportedError``. The
  encoder accepts either an enum member or its raw value, so
  ``M.model_validate({"color": "red"})`` works the same as
  ``M(color=Color.RED)``. ([#23])

### Fixed

- TaggedUnion-typed fields now JSON-round-trip correctly when the
  variant is itself a TaggedUnion. ``model_validate_json`` walks
  each nested ``{"kind": "...", ...}`` payload through the
  discriminator registry, instead of handing the dict straight to
  the variant-encoder (which expected a fully-constructed instance).
  Direct construction with a dict child works too:
  ``BinOp(left={"kind": "lit", "value": 1}, ...)`` dispatches the
  same way. ([#22])
- TaggedUnion-typed fields consult ``cls.__variants__`` *live* at
  encode and decode time, not snapshotted at field-classify time.
  Variants registered after a parent variant's field was classified
  (the canonical case is mutually recursive AST shapes:
  ``BinaryOp`` -> ``ListLiteral`` and ``ListLiteral`` -> ``BinaryOp``)
  participate fully, in either definition order. ([#24])

### Changed

- ``docs/guide/types.md`` documents the Path family and the
  StrEnum / IntEnum / value-typed Enum branches alongside a
  worked ``StrEnum`` example.
- ``docs/guide/unions.md`` documents recursive and mutually
  recursive variants, dict-dispatch on construction, and the JSON
  round-trip contract.

[#21]: https://github.com/panproto/didactic/issues/21
[#22]: https://github.com/panproto/didactic/issues/22
[#23]: https://github.com/panproto/didactic/issues/23
[#24]: https://github.com/panproto/didactic/issues/24

## [0.4.3] - 2026-05-05

### Fixed

- ``dx.TaggedUnion`` variant discriminator now accepts every spelling
  of ``Literal[...]``: bare ``Literal["x"]``, qualified
  ``typing.Literal["x"]``, and aliased imports
  (``from typing import Literal as L``). Under
  ``from __future__ import annotations`` the discriminator
  annotation arrives as a string; the variant check now evaluates
  that string in the class's defining module before applying the
  ``get_origin(...) is Literal`` check, instead of pattern-matching
  on the source text. Useful when the variant Model has a class
  also named ``Literal`` (e.g. an AST module exporting ``Literal``,
  ``Variable``, ``BinaryOp`` from a discriminator-tagged ``ASTNode``
  union root) so the user can keep the public API name. ([#18])

[#18]: https://github.com/panproto/didactic/issues/18

## [0.4.2] - 2026-05-05

### Fixed

- ``@dx.validates`` is no longer a silent no-op. The metaclass now
  walks ``target.__mro__`` for methods carrying the
  ``__didactic_validator__`` marker and stores them on the class as
  ``__field_validators__``; ``Model.__init__`` and ``Model.with_(...)``
  invoke them in the right order: ``dx.field(converter=...)`` first,
  then ``mode="before"`` validators on the raw value, then the
  encoder, then ``mode="after"`` validators on the canonical decoded
  value (re-encoded if the validator returned a different value).
  Validators may ``raise ValueError`` / ``raise TypeError`` to reject
  the input; failures surface as ``ValidationError`` entries with
  ``type="validator_error"`` and ``loc=(field_name,)``. Instance,
  ``@classmethod``, and ``@staticmethod`` shapes all work. Subclasses
  inherit a parent's validators; a subclass override that re-applies
  ``@validates`` replaces the inherited method, and a subclass that
  shadows the method without ``@validates`` deliberately disables
  validation for that field. ([#17])

### Changed

- ``docs/guide/validators.md`` was rewritten to document the
  ``raise ValueError`` / return-value-replaces-stored-value contract
  (the previous draft described a ``return bool`` shape that the
  runtime never implemented), and to cover ``mode="before"``,
  multi-field validators, multiple-validator chaining, inheritance
  semantics, and the three method shapes.

[#17]: https://github.com/panproto/didactic/issues/17

## [0.4.1] - 2026-05-05

### Fixed

- ``tuple[T, ...]``-typed fields now coerce list input to tuple at the
  encoder boundary instead of raising a bare ``AssertionError``.
  Mirrors Pydantic's affordance so call sites migrating across don't
  have to rewrite every ``indices=[0, 1, 2]`` literal. Non-iterable
  input still fails, but as a ``dx.ValidationError`` carrying the
  field name and a ``type_error`` entry, not as an ``AssertionError``
  from inside the encoder. ([#15])
- ``frozenset[T]``-typed fields coerce list, set, and tuple input the
  same way. Bare strings are still rejected (they would otherwise
  silently explode into ``frozenset({"a", "b", "c"})``).

[#15]: https://github.com/panproto/didactic/issues/15

## [0.4.0] - 2026-05-05

### Added

- ``ModelConfig.extra="ignore"`` is honoured: keyword arguments at
  construction (and dict keys at ``model_validate``) that don't match
  a declared field are silently dropped. ``with_()`` stays strict
  regardless; an unknown kwarg there is always a programming error.
  ([#11])
- Generic Models auto-parameterise on subscript. Both PEP 695 syntax
  (``class Range[T: int | float](dx.Model): ...``) and the legacy
  ``Generic[T]`` mixin form work. ``Range[int](min=0, max=10)`` returns
  an instance of a synthesised concrete subclass; the subclass is
  cached per type-arg tuple on the generic parent so repeated
  subscripts return the same class object and its ``Theory`` is built
  once. Substitution walks through nested generic shapes:
  ``tuple[T, ...]``, ``dict[str, T]``, ``T | None``,
  ``Annotated[T, *meta]``, ``Embed[T]``, ``Ref[T]``, and unions of
  these are all rewritten correctly. Class-level defaults
  (``min: T = 0``) and ``dx.field(...)`` metadata (``default``,
  ``default_factory``, ``description``, ``alias``, ``examples``,
  ``deprecated``, ``nominal``, ``usage_mode``, ``extras``,
  ``converter``) propagate from the generic parent onto the
  synthesised subclass. ([#12])
- ``read_class_annotations`` is part of the public surface (lifted
  from the underscore-prefixed ``_read_class_annotations``) and the
  metaclass's annotation-reader return type is
  ``dict[str, type | TypeVar | ForwardRef]`` to reflect what the
  PEP 695 generic-parameter path produces.

### Fixed

- Inherited field defaults survive on subclass. ``Child(Base)`` where
  ``Base`` declares ``id: str = "default-id"`` constructs cleanly
  with the inherited default. ``ModelMeta.collect_field_specs`` walks
  ancestor classes by copying their already-finalised ``FieldSpec``;
  it only re-runs ``_build_field_spec`` for the target class's own
  annotations. (Reading ``__dict__`` for ancestor classes lost their
  defaults because the metaclass strips field defaults from the
  class dict at the end of each Model's class-creation step.) ([#13])
- The deferred-TypeVar branch in ``_build_field_spec`` carries
  through every ``Field`` attribute (default, default_factory,
  converter, alias, description, examples, deprecated, nominal,
  usage_mode, extras), so a generic with ``value: T = dx.field(default=42,
  description="...")`` keeps that metadata available for
  parameterisation.

### Removed

- The leftover ``# Tracked in panproto/didactic#1.`` comment blocks
  from the v0.3.2 suppression unwind are stripped from every file in
  the workspace. They documented suppressions that no longer exist.

[#11]: https://github.com/panproto/didactic/issues/11
[#12]: https://github.com/panproto/didactic/issues/12
[#13]: https://github.com/panproto/didactic/issues/13

## [0.3.2] - 2026-05-04

### Changed

- panproto pin bumped to ``>=0.43.1``. panproto 0.43.1 ships
  corrected ``_native.pyi`` stubs for ``create_theory``
  (``Mapping[str, object]``) and ``colimit_theories``
  (``(t1, t2, shared)``), so didactic now calls these directly
  again. Tracking issue panproto/panproto#72 closed upstream.

### Fixed

- All strategic per-file pyright suppressions tracked under ([#1])
  are now removed and the underlying issues are fixed structurally.
  ``uv run pyright`` reports 0 errors with no per-file
  ``# pyright: report*=false`` directives outside the documented
  ``CONTRIBUTING.md`` carve-out (the ``field()`` overload pattern,
  which pyright in strict mode cannot reconcile with the
  ergonomics that drive the carve-out's existence).
- The fixes touch every package: typed ``cast`` boundaries where
  panproto returns wider types than didactic's narrower public
  surface, ``isinstance`` narrowing on ``model_dump`` results in
  tests, ``Model.model_validate({...})`` swaps for negative tests
  passing wrong-typed kwargs, public re-exports of
  underscore-prefixed names that tests already reach for, and a
  handful of small refactors (a typed kwargs dict in
  ``_resolve_config``, a structured cast at the metaclass
  annotation boundary, ``__provenance__`` gated behind
  ``TYPE_CHECKING`` so the metaclass does not register it as a
  Model field).
- ``TypeForm`` widened to include ``TypeAliasType`` and
  ``GenericAlias``. The static type now matches what
  ``classify`` / ``unwrap_annotated`` accept at runtime.
- ``FieldSpec.annotation`` widened to ``TypeForm | TypeVar |
  ForwardRef``. The metaclass walks generic-parameter and
  forward-string annotations as a real path; the type now reflects
  it.
- ``Repository.resolve_ref`` raises ``panproto.VcsError`` when
  the underlying call returns ``None`` instead of silently
  violating its ``-> str`` return type.
- Removed an unused ``_class_axiom_eq`` helper from
  ``theory/_theory.py``. The helper was a stub for a future
  eqs-emission path; it lives in the git history and will return
  when the panproto-Expr parser hookup lands.
- ``Lens[A, B]`` is now ``Lens[A, B, C]`` in
  ``check_lens_laws`` so the complement type carries through to
  ``dx.testing.check_lens_laws``; tests parameterise as
  ``dx.Lens[User, User, str]``.
- Settings package: replaced ``# type: ignore`` directives by
  routing yaml through ``importlib.import_module``, adding a real
  ``fetch`` method to the ``_Source`` base, casting at the
  ``Opaque -> JsonValue`` loader boundary, splitting the
  ``argparse.Namespace`` vs ``Mapping`` branches, and gating
  ``__provenance__`` behind ``TYPE_CHECKING`` so the metaclass
  does not register it as a Model field.

[#1]: https://github.com/panproto/didactic/issues/1

## [0.3.1] - 2026-05-01

### Fixed

- Sum-sort encoders (closed Model-ref recursive aliases and TaggedUnion
  field types) now route the chosen variant through ``model_dump_json``
  instead of bare ``model_dump``, so any nested
  ``tuple[Embed[T], ...]`` / ``dict[str, Embed[T]]`` / arbitrary
  Model-containing structure inside the variant gets the JSON-safe
  walk. Previously such payloads raised
  ``Object of type X is not JSON serializable`` from ``json.dumps``.
  ([#7])
- ``Embed[Inner]`` round-trip via ``model_dump_json`` /
  ``model_validate_json`` no longer asserts when ``Inner`` has a
  ``tuple[T, ...]`` (or any ``from_json``-coerced) field. The embed
  translation now routes inner JSON payloads through
  ``model_validate_json`` so per-field ``from_json`` runs at every
  level (e.g. JSON list to tuple coercion). ([#8])
- ``model_dump`` evaluates ``inner_kind == "sum"`` before the
  ``isinstance(value, Model)`` branch, so a Model variant of a
  sum-sort field is dumped with its constructor tag instead of
  collapsing to the variant's record dict. Previously a recursive
  alias whose Model arm was the current value lost its dispatch
  info on the dump side; the JSON round-trip then raised
  ``unknown constructor`` on decode.
- ``embed_schema_uri`` walks nested Model-containing fields via
  ``model_dump_json`` so the returned dict is always serialisable;
  previously failed with ``TypeError`` when the source instance had
  a ``tuple[Embed[T], ...]`` field.

### Changed

- Recursive Model-ref alias encoders prefer the ``tuple`` constructor
  over the ``list`` constructor when both arms are declared, even for
  Python ``list`` input. This keeps the encoded storage form
  canonical: round-tripping a Python list and re-encoding produces
  the same constructor name and the same storage string, restoring
  ``Model`` equality across the round-trip.

[#7]: https://github.com/panproto/didactic/issues/7
[#8]: https://github.com/panproto/didactic/issues/8

## [0.3.0] - 2026-05-01

### Added

- Recursive type aliases whose arms include `dx.Model` subclasses now
  translate to a panproto-native closed sum sort. The motivating shape
  is a `Component` alias mixing primitives, Models, and JSON-compatible
  containers; the alias name becomes the panproto sort, with one
  `Operation` per arm declared as a constructor and the sort's
  `SortClosure` set to `Closed` against that constructor list. Wire
  format for an arm value is a single-key JSON object whose key is
  the constructor name (matches panproto's term-of-closed-sort
  encoding). Lists round-trip as tuples to satisfy the tuple-based
  `FieldValue` invariant. Cycles in the value graph raise
  `ValueError` rather than recurse. ([#2])
- `dx.TaggedUnion` subclasses are now usable directly as a field value
  type. `dict[str, Parameter]`, `tuple[Parameter, ...]`, and a bare
  `param: Parameter` annotation all work, with dispatch via the
  variant's discriminator field. The translation contributes a closed
  sum sort and per-variant constructor ops to the parent Model's
  Theory; the on-wire format is the variant's natural `model_dump`
  (no envelope, since the discriminator is already in the payload).
  ([#5])
- `TypeTranslation` gains optional `auxiliary_sorts` and
  `auxiliary_ops` tuples that let a translation contribute extra
  panproto sort and operation declarations to the parent Model's
  Theory. Currently produced by the recursive Model-ref alias and
  TaggedUnion translations; `build_theory_spec` walks them and
  dedupes by name. Empty for every other translation.
- `inner_kind = "sum"` joins the documented set of `TypeTranslation`
  inner-kind values. `model_dump` routes sum-sort fields through their
  encoder so the constructor-tag dispatch survives JSON round-trip.

### Notes

- Recursive aliases that aren't pure JSON-shape and aren't
  Model-ref-shape (e.g. one admitting `bytes`, `Decimal`, or a
  non-Model class) continue to raise `TypeNotSupportedError` with a
  clear message.
- Panproto's `Theory.sorts` and `Theory.ops` attributes are list-typed
  at runtime, contrary to the shipped `_native.pyi` stub which marks
  them as methods. Tests that introspect a built Theory treat them
  as data.

[#2]: https://github.com/panproto/didactic/issues/2
[#5]: https://github.com/panproto/didactic/issues/5

## [0.2.0] - 2026-05-01

### Added

- Bare PEP 695 type aliases now translate transparently. `type Kind =
  Literal["a", "b", "c"]` is accepted as a Model field annotation; the
  classifier unwraps the alias before dispatching. ([#2])
- Union of primitive scalars is a translatable field type. `int | str`,
  `float | str`, `int | float | str`, and the same unions inside
  `dict[str, V]` and `T | None` are accepted. The synthesised
  panproto sort name is `"Union <a> <b> ..."` in canonical order; the
  encoder JSON-encodes the value, and the decoder dispatches on the
  resulting Python type. ([#2], [#3])
- JSON-shaped recursive type aliases translate to a single opaque
  panproto sort named after the alias. The motivating shape is the
  canonical `JsonValue` alias (`str | int | float | bool | None |
  list[X] | tuple[X, ...] | dict[str, X]` with `X` self-referential).
  The encoded form is `json.dumps(value)`; the decoder parses and
  recursively coerces lists to tuples to satisfy didactic's
  tuple-based `FieldValue` type. Recursive aliases that are *not*
  JSON-shaped (e.g. one admitting `bytes`) raise
  `TypeNotSupportedError` with a clear message rather than failing
  silently. ([#2])

[#2]: https://github.com/panproto/didactic/issues/2
[#3]: https://github.com/panproto/didactic/issues/3

## [0.1.0] - 2026-05-01

### Added

- `dx.Model` and `dx.BaseModel` with frozen, immutable instances backed
  by a panproto Theory built lazily on first `__theory__` access.
- `dx.field(...)` descriptor with default, default_factory, alias,
  description, examples, deprecated flag, nominal-id flag, custom
  converters (PEP 712), and pass-through extras.
- `dx.ModelConfig` for class-level configuration.
- `dx.Ref[T]` non-owning cross-vertex references.
- `dx.Embed[T]` owned sub-vertex composition.
- `dx.TaggedUnion` discriminated unions with subclass dispatch.
- `dx.Lens[A, B]`, `dx.Iso[A, B]`, `dx.Mapping[A, B]` lens classes
  with composition, identity, and `inverse()` for `Iso` chains.
- `@dx.computed` derived attributes for serialisation.
- `dx.axiom("...")` class-level axioms collected on
  `cls.__class_axioms__`.
- `@dx.validates(field_name)` Python-side validators.
- JSON / pickle serialisation with per-field re-coercion.
- `dx.register_migration(...)` / `dx.migrate(...)`: schema migrations
  as registered lenses keyed by **structural fingerprint** of the
  Theory spec, robust to class renames and re-imports.
- `dx.save_registry(path)` / `dx.load_registry(path)`: human-readable
  registry dumps for diagnostic and audit purposes.
- `dx.Repository.init(...)` / `Repository.open(...)`: filesystem-backed
  panproto repository wrapper. `add` accepts either a panproto
  `Schema` or a `dx.Model` class (synthesised via
  `Protocol.from_theories`). Branches, refs, tags, and log all
  exposed.
- `dx.DependentLens`: schema-parametric lens family wrapping
  `panproto.ProtolensChain` (auto-generation, JSON round-trip,
  composition, fusion, instantiation).
- `dx.resolve_backrefs(target, candidates, *, via)` plus
  `dx.ModelPool` for in-memory backref resolution.
- Theory colimit on multiple inheritance: `class D(B, C)` builds the
  panproto pushout over the lowest common Model ancestor.
- `dx.testing.verify_iso(iso, strategy)` for property-test law checks.
- `didactic-pydantic.from_pydantic(...)`: structural conversion of a
  Pydantic v2 `BaseModel` to a `dx.Model` subclass.
- `didactic-pydantic.to_pydantic(...)`: the inverse direction, for
  FastAPI / OpenAPI consumers.
- mkdocs documentation site with narrative guides and a full API
  reference, validated in CI under `--strict` mode.
- Runnable examples in `examples/`.

### Known issues

- A handful of files carry per-file pyright suppressions for noise that
  the strict-mode checker cannot resolve without a deeper refactor.
  Each suppression is inline-commented with the rule list and the
  reason. Tracked in [issue #1][post-release-pyright]; the suppressions
  will be replaced with the real fixes in a v0.1.x patch release.
  [post-release-pyright]: https://github.com/panproto/didactic/issues/1

### Notes

- Targets Python 3.14 and panproto 0.40+.
- The structural fingerprint normalises a Model's display name in the
  spec before hashing, so two structurally identical Models share a
  registry entry.
