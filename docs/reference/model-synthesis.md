# Model synthesis (inbound)

Reconstruct [Model][didactic.api.Model] classes from panproto Theory
specs: the faithful inverse of
[build_theory_spec][didactic.theory._theory.build_theory_spec]. For a
hand-written Model, the regenerated class's forward spec equals the
original's.

Closed sum sorts round-trip: a `dx.TaggedUnion` field rebuilds into a
union root with one variant per constructor, and a Model-ref recursive
alias rebuilds into an equivalent `type` alias. Reconstruction is
faithful at the Theory-spec level (structure), not at the level of
Python annotations or field metadata; the function docstrings below
spell out the recoverable / unrecoverable split.

::: didactic.api.model_from_spec

::: didactic.api.models_from_specs

::: didactic.api.model_from_theory
