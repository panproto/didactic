# Fingerprints

A structural fingerprint is a stable, content-addressed identifier
for a Model. didactic uses fingerprints for two things: keying the
[migration registry](../guide/migrations.md) and labelling
[self-describing JSON](../guide/self-describing.md) payloads.

## The algorithm

1. Build the panproto-shaped spec dict for the Model
   (`didactic.theory._theory.build_theory_spec`).
2. Replace every occurrence of the Model's display name with the
   placeholder `<self>`. This includes the top-level `name` field,
   the matching sort name, and the per-field sort prefixes.
3. Render the result to canonical JSON (sorted keys, no whitespace,
   ASCII-safe escaping).
4. Take the SHA-256 hex digest.

The result is a 64-character lowercase hex string. The full
implementation lives in `didactic.migrations._fingerprint`.

## What gets identified

Two Models share a fingerprint when they have:

- the same field names and order
- the same per-field sort kinds
- the same axioms (in declaration order)
- the same panproto-side equations

Two Models with the same fields but different class names share a
fingerprint. Two Models that differ in any of the above produce
different fingerprints.

## Why structural

didactic's migration registry keys on a structural fingerprint
rather than a name-included one because the user's class name is
not part of the data's shape. A library that renames `User` to
`Account` while keeping the fields the same should not break stored
migrations.

The cost is that two semantically distinct Models with the same
field shape collide. In the migration setting this is harmless: a
migration registered for one shape applies to any Model with that
shape, and the migration's lens carries enough state to construct
the right output type.

## Stability across releases

The fingerprint depends on:

- the spec-format shape (didactic's, not panproto's)
- the SHA-256 algorithm

Both are committed to. A spec-format change in didactic is a
breaking release and ships with a one-shot fingerprint migrator that
re-hashes any on-disk registry. The hash algorithm will not change.

The fingerprint is **independent** of:

- panproto's wire format (msgpack settings, blake3 vs other hash)
- panproto's `Theory.Serialize` impl
- panproto's `Ident::std::hash::Hash` (which is process-local; see
  the upstream issue notes for context)

Drift in any of these does not invalidate stored fingerprints.

## Inspecting a fingerprint

```python
from didactic.migrations._fingerprint import (
    fingerprint, structural_fingerprint
)
from didactic.theory._theory import build_theory_spec


class User(dx.Model):
    id: str
    email: str


structural_fingerprint(build_theory_spec(User))
# '06ac976d...'

# The non-structural fingerprint includes the class name.
fingerprint(build_theory_spec(User))
# '94f3a5b1...'
```

The CLI surfaces the structural fingerprint in `didactic schema show`.
