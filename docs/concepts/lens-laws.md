# Lens laws

Lenses obey laws. didactic ships test fixtures that check them on
arbitrary inputs.

## GetPut

For a `Lens[A, B]`:

```text
backward(*forward(a)) == a   for all a in A
```

Reading a value, then writing it back via the same lens, recovers the
original. This is the law that says the lens's complement actually
captures the missing information.

## PutGet

```text
forward(backward(b, c)) == (b, c)   for all b in B, c in Complement
```

If you write a `B` via the lens, reading it again through the lens
produces exactly the same `B` you wrote, and the same complement.

## Iso laws

For an `Iso[A, B]` (which is a Lens with no complement):

```text
backward(forward(a)) == a   for all a in A
forward(backward(b)) == b   for all b in B
```

The two directions are total inverses.

## Composition

Lens composition (`>>`) is associative. For `Lens[A, B]`,
`Lens[B, C]`, `Lens[C, D]`:

```text
(ab >> bc) >> cd  ==  ab >> (bc >> cd)
```

The identity Iso `Iso[A, A]` is a left and right identity for `>>`.

## Verifying laws on your code

`dx.testing.verify_iso` runs the Iso round-trip law on Hypothesis
samples:

```python
from hypothesis import strategies as st


dx.testing.verify_iso(
    SwapNameOrder(),
    st.builds(FirstLast, given=st.text(), family=st.text()),
)
```

The other helpers cover the rest:

| helper | law |
| --- | --- |
| `verify_iso(iso, strategy)` | iso round-trip |
| `check_lens_laws(lens, strategy)` | GetPut for a non-iso lens |
| `verify_mapping(m, strategy)` | mapping is a function (deterministic) |
| `verify_lens_composition(L1, L2, strategy)` | `(L1 >> L2)(x) == L2(L1(x))` |
| `verify_iso_inverse(iso)` | `iso.inverse().inverse()` is the same iso |
| `verify_migration_round_trip(iso, strategy)` | iso preserves information |

Each helper runs Hypothesis under the hood and surfaces a clear
assertion failure on any sample that violates the law.

## Why this matters

Migrations are lenses. A migration that violates GetPut loses
information, which means migrating a payload forward and then
walking back through the inverse produces a payload different from
the original. For an Iso migration this is a bug.

The fixtures let you assert the law in your test suite, catch
regressions early, and ship migrations that are documented to round
trip. Pydantic offers no analogue: there is no notion of a lens, no
notion of an inverse migration, and no machine-checkable round-trip
law.
