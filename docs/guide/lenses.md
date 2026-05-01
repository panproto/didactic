# Lenses

A lens is a function-like object that maps between two Model
classes. didactic ships three subtypes, in increasing strictness:

| type | shape | round-trip law |
| --- | --- | --- |
| `Mapping[A, B]` | `A -> B` | none; one-way |
| `Lens[A, B]` | `A -> (B, complement)` and `(B, complement) -> A` | GetPut and PutGet |
| `Iso[A, B]` | `A -> B` and `B -> A` | total bijection |

## Defining an Iso

```python
import didactic.api as dx


class FirstLast(dx.Model):
    given: str
    family: str


class LastFirst(dx.Model):
    family: str
    given: str


class SwapNameOrder(dx.Iso[FirstLast, LastFirst]):
    def forward(self, n: FirstLast) -> LastFirst:
        return LastFirst(family=n.family, given=n.given)

    def backward(self, n: LastFirst) -> FirstLast:
        return FirstLast(given=n.given, family=n.family)


iso = SwapNameOrder()
iso(FirstLast(given="Ada", family="Lovelace"))
# LastFirst(family='Lovelace', given='Ada')
```

The Iso is also callable: `iso(x)` is `iso.forward(x)`.

## Defining a Lens

For a transformation that loses information in the forward direction
but stores enough on the side to recover it:

```python
class WithComment(dx.Model):
    payload: str
    comment: str


class WithoutComment(dx.Model):
    payload: str


class StripComment(dx.Lens[WithComment, WithoutComment]):
    def forward(self, w: WithComment) -> tuple[WithoutComment, str]:
        return WithoutComment(payload=w.payload), w.comment

    def backward(self, view: WithoutComment, comment: str) -> WithComment:
        return WithComment(payload=view.payload, comment=comment)
```

## Composing lenses

`>>` composes by chaining forward and backward through both lenses:

```python
ab >> bc        # Lens[A, C]
```

Composition is associative; identity is the trivial Iso.

## Verifying lens laws

`dx.testing.verify_iso` runs the iso round-trip law on Hypothesis
samples:

```python
from hypothesis import strategies as st

dx.testing.verify_iso(
    SwapNameOrder(),
    st.builds(FirstLast, given=st.text(), family=st.text()),
)
```

For a non-iso lens, use [check_lens_laws][didactic.api.testing.check_lens_laws]
which runs GetPut. The complementary helpers
[verify_mapping][didactic.api.testing.verify_mapping],
[verify_lens_composition][didactic.api.testing.verify_lens_composition],
[verify_iso_inverse][didactic.api.testing.verify_iso_inverse], and
[verify_migration_round_trip][didactic.api.testing.verify_migration_round_trip]
cover the rest of the algebraic laws.

## Schema-parametric lenses

For a lens family that operates on many concrete schemas (Avro to
OpenAPI conversion, for instance), use
`didactic.api.DependentLens`. It wraps panproto's
`ProtolensChain` and produces a concrete `Lens` once instantiated
against a pair of schemas. See the
[reference page](../reference/lens.md#didactic.api.DependentLens) for the full
surface.
