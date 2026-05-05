# Inheritance

didactic supports both single and multiple inheritance. The Theory
derivation handles each in a different way:

- Single inheritance flattens the field set. The metaclass walks
  the MRO when collecting field specs, so `class B(A)` simply has
  every field from `A` plus its own.
- Multi inheritance triggers a panproto colimit (pushout) of the
  parent Theories over their lowest common ancestor.

## Single inheritance

```python
import didactic.api as dx


class A(dx.Model):
    x: int


class B(A):
    y: int


b = B(x=1, y=2)
b.x      # 1
b.y      # 2
```

`B.__field_specs__` contains both `x` and `y`. `B.__theory__` is the
flat Theory built from the merged spec; no colimit is involved.

Inherited axioms (`__axioms__`) are also collected: `B` is checked
against both its own and `A`'s.

### Inherited defaults

A subclass inherits the parent's defaults verbatim. Re-declaring a
field on the subclass replaces the inherited spec; if the
re-declaration omits a default, the field becomes required on the
subclass (matching dataclass semantics).

```python
class Base(dx.Model):
    id: str = "default-id"
    name: str = "default-name"


class Child(Base):
    extra: str = "x"


Child()
# Child(id='default-id', name='default-name', extra='x')


class Override(Base):
    id: str = "child-id"   # replaces the parent's default
    # name keeps the parent's "default-name"


class Required(Base):
    id: str   # no default re-declaration -> required


Required()  # raises ValidationError: required field 'id' not supplied
```

The parent's `default_factory`, `description`, `alias`, `examples`,
and other Field metadata flow through alongside the default. Each
subclass instance still calls the factory fresh.

## Multi inheritance

```python
class Shared(dx.Model):
    id: str


class Reads(Shared):
    read_count: int = 0


class Writes(Shared):
    write_count: int = 0


class Both(Reads, Writes):
    note: str = ""
```

When `Both`'s Theory is built, didactic walks `Both`'s immediate
parents (`Reads` and `Writes`), finds their lowest common ancestor in
the Model lineage (`Shared`), and computes the colimit:

```text
panproto.colimit_theories(Reads.__theory__, Writes.__theory__, Shared.__theory__)
```

The result is the categorical pushout. panproto validates that the
join is consistent (the shared sub-theory's sorts and operations
appear with the same shape in both parents).

For three or more parents, the colimit is computed left-to-right.
The end result is the same panproto Theory you would get by listing
all the fields on `Both` directly, but going through `colimit_theories`
asserts that the parents' Theories are compatible at the categorical
level.

## What goes wrong, and how

A multi-inheritance setup that produces an inconsistent join surfaces
as a `panproto.GatError` at first `__theory__` access (which is
typically your first interesting use of the class). Common causes:

- Two parents declaring fields with the same name but different
  types. didactic catches this earlier as a Python-side metaclass
  error, but a panproto-side variant can still surface for richer
  shapes.
- Two parents with conflicting axioms. The colimit refuses to merge
  contradictory equations.

If you see a `GatError`, the message names the offending sort or
equation; the fix is usually to factor the conflict into a common
ancestor or to drop one branch.
