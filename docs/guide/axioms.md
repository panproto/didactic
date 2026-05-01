# Axioms

An axiom is a class-level expression that must hold of every
instance. Declare axioms in `__axioms__`:

```python
import didactic.api as dx


class Range(dx.Model):
    low: int
    high: int

    __axioms__ = [
        dx.axiom("low >= 0", message="low must be non-negative"),
        dx.axiom("low <= high", message="low must not exceed high"),
    ]
```

Axioms run after type translation and per-field validators. A failure
raises [didactic.api.ValidationError][didactic.api.ValidationError] with an
`axiom_failed` entry; the entry's `msg` is the axiom's `message`
keyword (or the expression text, when no message is given).

## Expression syntax

Axiom expressions use the panproto-Expr surface syntax. The set
didactic's evaluator currently supports:

| operator | example |
| --- | --- |
| equality | `x == 0`, `x /= 0` |
| ordering | `x < 0`, `x <= 0`, `x > 0`, `x >= 0` |
| boolean | `a && b`, `a || b`, `not x` |
| arithmetic | `x + y`, `x - y`, `x * y`, `x / y`, `x % y`, `-x` |
| length | `len(xs)` |

The free variables in an axiom must match field names on the Model.
Inherited fields are visible: an axiom on a base class evaluates
against the derived class's environment.

## Inheritance

Axioms are collected across the MRO. A subclass automatically inherits
its parents' axioms; declaring fresh ones in `__axioms__` extends the
list, it does not replace it.

```python
class Bounded(dx.Model):
    x: int
    __axioms__ = [dx.axiom("x >= 0")]


class Tighter(Bounded):
    __axioms__ = [dx.axiom("x <= 100")]


Tighter(x=42)            # ok
Tighter(x=-1)            # raises (parent axiom)
Tighter(x=200)           # raises (own axiom)
```

## What axioms cannot do (yet)

The panproto-Expr surface syntax is broader than the subset didactic
currently evaluates. Constructs the evaluator does not yet handle
include `forall`, `exists`, `let`, `case`, lambdas, and graph
traversal. An axiom using one of those parses successfully but the
evaluator raises `NotImplementedError` at construction.

You can still declare such axioms; they are recorded in
`__class_axioms__` and surface in tooling that walks the Theory's
equations. The construction-time check is the part that requires
evaluator support.

## When to use axioms vs validators

| if... | use |
| --- | --- |
| one field, custom logic | `@validates(field_name)` |
| multiple fields, expressible in the surface syntax | `__axioms__` |
| multiple fields, custom Python logic | a `@validates` on any field whose body checks the others |
