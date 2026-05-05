# Guides

Task-oriented walkthroughs of each feature. Each page assumes
familiarity with the [Tutorial](../tutorial/index.md) and answers a
specific question of the form "how do I do X with didactic".

## Modelling

- [Models](models.md) covers the authoring patterns: declaring fields,
  controlling `__init__`, immutable updates with `.with_(...)`, and
  inheritance.
- [Fields](fields.md) is the per-field reference for `dx.field(...)`:
  defaults, factories, aliases, descriptions, examples, deprecation.
- [Types](types.md) lists every built-in scalar type and how to add
  your own.
- [References and embedding](refs.md) covers `Ref[T]`, `Embed[T]`,
  `Backref[T]`, and the in-memory `ModelPool` for backref resolution.
- [Tagged unions](unions.md) covers `dx.TaggedUnion` for
  discriminated unions.
- [Computed and derived fields](computed-derived.md) covers
  `@dx.computed` (recomputed every read) and `@dx.derived` (computed
  once at construction).
- [Inheritance](inheritance.md) explains how `class B(A)` produces a
  panproto Theory colimit and how multi-inheritance behaves.
- [Generic Models](generics.md) covers PEP 695 generic class syntax,
  the `Generic[T]` mixin, subscript synthesis, default propagation,
  and substitution through nested generic shapes.

## Validation

- [Validators](validators.md) covers `@dx.validates` and the shape of
  `ValidationError`.
- [Axioms](axioms.md) covers class-level constraints declared via
  `__axioms__` and the supported expression syntax.

## Schema evolution

- [Lenses](lenses.md) covers `dx.Lens`, `dx.Iso`, `dx.Mapping`,
  composition, and the law fixtures in `dx.testing`.
- [Migrations](migrations.md) covers `register_migration`, `migrate`,
  the structural fingerprint, and the persistence helpers.
- [Schema diff](diff.md) covers `dx.diff` and `dx.classify_change`
  for breaking-change detection in CI.

## Output and integration

- [Code generation](codegen.md) covers `Model.emit_as(target)`,
  custom emitters, JSON Schema, Avro, and the source-language
  emitters.
- [Self-describing JSON](self-describing.md) covers content-addressed
  schema URIs in payloads.
- [VCS repository](repository.md) covers `dx.Repository.init` and the
  filesystem-backed schema store.
- [CLI](cli.md) covers the `didactic` command-line tool.

## Sibling packages

- [Pydantic interop](pydantic.md) covers
  `from_pydantic` and `to_pydantic` from `didactic-pydantic`.
- [Settings](settings.md) covers `didactic-settings`: env vars,
  dotenv, structured config files, and CLI args, with
  per-field provenance.
- [FastAPI](fastapi.md) covers `didactic-fastapi` for using `dx.Model`
  types as request and response bodies.
