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

Axiom expressions use the panproto-Expr surface syntax with a
small set of Python-friendly synonyms applied at parse time. Either
spelling works; pick whichever reads more naturally for the constraint.

| category | examples |
| --- | --- |
| equality | `x == 0`, `x /= 0`, `x != 0` |
| ordering | `x < 0`, `x <= 0`, `x > 0`, `x >= 0` |
| boolean | `a && b`, `a or b`, `not x` |
| arithmetic | `x + y`, `x - y`, `x * y`, `x / y`, `x % y`, `-x` |
| absent value | `a == null`, `a == None`, `a == Nothing`, `a is null`, `a is not null` |
| if-then-else | `if cond then x else y` |
| `let` | `let s = a + b in s > 0` |
| list literal | `[1, 2, 3]` |
| field access | `a.b` (resolves via `getattr`) |
| concat | `xs ++ ys` |
| length / head / tail / abs | `len xs`, `head xs`, `tail xs`, `abs x` |
| min / max / sum / and / or / all / any / elem | `min a b`, `elem x xs` |
| map / filter (with lambda) | `map (\x -> x + 1) xs`, `filter (\x -> x > 0) xs` |
| `Just` / `Nothing` | `Just x`, `a == Nothing` |

The Python-friendly synonyms are pure surface sugar; they get
rewritten before parsing:

- `!=`  becomes `/=` (panproto's "not equal").
- `and` / `or` keywords become `&&` / `||`.
- `null` / `None` become `Nothing`.
- `X is null` becomes `X == Nothing`; `X is not null` becomes
  `X /= Nothing`.

The substitutions respect string literals: nothing inside `"..."` or
`'...'` is rewritten.

### Optional fields

`T | None` fields hold either a `T` or `None`. To check whether an
optional field is set, compare to `null` / `None` / `Nothing`:

```python
class Cfg(dx.Model):
    bounded: bool = False
    min_value: float | None = None

    __axioms__ = [
        dx.axiom(
            "if bounded then min_value /= null else true",
            message="bounded models must set min_value",
        ),
    ]
```

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

panproto's parser accepts a few constructs that the runtime
evaluator deliberately does not implement: `forall` and `exists`
quantifiers, `case`-style multi-arm pattern matching beyond the
`if/then/else` shape, and graph-traversal builtins. An axiom using
one of those parses successfully but the evaluator raises
`NotImplementedError` at construction.

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
