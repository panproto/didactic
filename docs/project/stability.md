# Stability

didactic is pre-1.0. The public API surface is the symbols listed in
the [API reference](../reference/index.md) plus the documented
attributes on `dx.Model` (`__field_specs__`, `__class_axioms__`,
`__computed_fields__`, `__theory__`).

## What is stable

The following are committed to across minor releases:

- The user-facing names and signatures of every documented symbol.
- The structural fingerprint algorithm.
- The didactic-shape spec dict produced by
  ``didactic.theory._theory.build_theory_spec``.
- The migration registry's on-disk JSON format.
- The lens authoring API (`Lens`, `Iso`, `Mapping`, `>>`,
  `inverse()`).
- The CLI subcommand names and exit codes.

A change to any of these in a non-major release ships with a
deprecation path or a one-shot migrator.

## What is not stable

- The internal panproto encoding. The bridge in
  ``didactic.theory._theory`` may evolve as panproto's accepted
  spec shape evolves; this does not affect the user-facing API.
- The set of `ValidationErrorEntry.type` discriminator values.
  New types may be added; do not pattern-match on the closed set.
- The exact wire format of generated artefacts (Avro schema layout,
  Rust source style). Output is functionally correct but its
  formatting may change with panproto upgrades.

## Versioning

didactic follows [Semantic Versioning](https://semver.org/) once it
hits 1.0. Pre-1.0, minor releases may introduce breaking changes;
each is documented in the [Changelog](changelog.md).

## panproto compatibility

didactic pins panproto via a `>=` floor (currently `panproto>=0.42`).
panproto's wire format may change between minor releases; didactic
absorbs the difference internally so `import didactic` keeps working
across panproto upgrades within the supported range.

## Breaking change check

Use the `didactic check breaking` CLI to assert that a Model change
is non-breaking:

```bash
didactic check breaking myapp.models:UserV1 myapp.models:UserV2
```

Run this in CI on every PR. The exit code distinguishes the three
outcomes (compatible, breaking, user error). See
[Guides > Schema diff](../guide/diff.md).
