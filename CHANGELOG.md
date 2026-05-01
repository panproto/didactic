# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
