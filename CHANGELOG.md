# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
