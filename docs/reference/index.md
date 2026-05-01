# API reference

Per-symbol documentation generated from the source. Use this when
you know what you want to call and need the exact signature and
parameter list.

## Models and fields

- [Model](model.md): the `dx.Model` base, plus `BaseModel`,
  `ModelConfig`, `RootModel`, `TypeAdapter`.
- [Field](field.md): `dx.field()` and `FieldSpec`.
- [Validators](validators.md): `@dx.validates`, `ValidationError`.
- [Refs](refs.md): `Ref`, `Embed`, `Backref`.
- [Backref resolution](backref.md): `resolve_backrefs`, `ModelPool`.
- [Tagged unions](unions.md): `TaggedUnion`.
- [Computed](computed.md), [Derived](derived.md).
- [Axioms](axioms.md): `Axiom`, `axiom`, `check_class_axioms`.
- [Types](types.md): `EmailStr`, `HttpUrl`, `SecretStr`, `Json`.

## Schema evolution

- [Lens](lens.md): `Lens`, `Iso`, `Mapping`, `DependentLens`,
  `lens` decorator.
- [Migrations](migrations.md): `register_migration`, `migrate`,
  `save_registry`, `load_registry`.
- [Schema diff](diff.md): `diff`, `classify_change`,
  `is_breaking_change`.
- [Synthesis](synthesis.md): `synthesise_migration`,
  `SynthesisResult`.

## Theory and fingerprints

- [Theory bridge](theory.md): `build_theory`, `build_theory_spec`.
- [Fingerprints](fingerprint.md): `fingerprint`,
  `structural_fingerprint`, `canonical_json_bytes`.

## Output and integration

- [Code generation](codegen.md): `emit_as`, `Emitter`, `IndentWriter`,
  `register_emitter`, `json_schema_of`, `write`.
- [Self-describing](self-describing.md): `schema_uri`,
  `embed_schema_uri`, `FingerprintRegistry`,
  `validate_with_uri_lookup`.
- [Repository](repository.md): `Repository`.
- [Testing](testing.md): the lens-law fixtures.
- [CLI](cli.md): `didactic.cli.main`.

## Sibling packages

- [Pydantic adapter](pydantic-adapter.md): `from_pydantic`,
  `to_pydantic`.
- [Settings](settings.md): `Settings`, `EnvSource`, `DotEnvSource`,
  `FileSource`, `CliSource`.
- [FastAPI](fastapi.md): `as_request`, `as_response`,
  `register_validation_handler`.
