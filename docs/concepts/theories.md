# Theories

A panproto `Theory` is a generalised algebraic theory: a finite
description of a data shape in terms of sorts, operations, and
equations. didactic produces one Theory per Model class.

## Sorts

Every Model class gets a primary sort named after the class, plus
one constraint sort per field:

```text
class User(dx.Model):
    id: str
    email: str
```

becomes (in spec form):

```text
sorts = [
    {"name": "User",       "kind": "Structural"},
    {"name": "User_id",    "kind": {"Val": "Str"}},
    {"name": "User_email", "kind": {"Val": "Str"}},
]
```

The primary sort is `Structural` (a vertex kind); the constraint
sorts are `Val[ValueKind]` (a value carrier with a typed payload).

## Operations

Each field becomes an accessor operation from the primary sort to
its constraint sort:

```text
ops = [
    {"name": "id",    "inputs": [["self", "User", "No"]], "output": "User_id"},
    {"name": "email", "inputs": [["self", "User", "No"]], "output": "User_email"},
]
```

`Ref[T]` and `Embed[T]` produce operations whose output is `T`'s
primary sort, which gives the Theory an explicit edge to the target
class.

## Equations

Class-level [axioms](../guide/axioms.md) and `annotated-types`
constraints become equations on the Theory. didactic's spec-builder
collects them, panproto validates that the set is consistent, and
the resulting Theory carries the equations as first-class data.

## Why use a Theory

A Theory is a content-addressed, language-agnostic description of a
data shape. Three things follow:

1. Two Models with the same Theory are interchangeable. The
   structural fingerprint (see [Fingerprints](fingerprints.md)) is
   computed from the Theory, so two structurally identical Models
   share a migration entry, share a schema URI, and produce
   byte-identical schema artefacts when emitted.
2. A Theory can be exported to many target formats. panproto's
   `IoRegistry` and `AstParserRegistry` consume the Theory and emit
   Avro, OpenAPI, FHIR, Protobuf, Rust, TypeScript, etc.
3. Theory operations compose categorically. `colimit_theories`
   computes the pushout of two Theories over a shared sub-theory,
   which is what `class B(A)` does internally and what migration
   synthesis builds on.

## When to use it directly

Most code never touches `panproto.Theory` directly. Reach for it when:

- You need to know the canonical key of a field (`spec.translation.sort`).
- You are writing a custom emitter and want to walk the Theory's
  ops and equations.
- You want to call `panproto.colimit_theories` directly for a Models
  combination outside the inheritance graph.

`Foo.__theory__` is the entry; `didactic.theory.build_theory_spec(Foo)`
returns the panproto-shape dict if you only need that.
