# GADTs and indexed families

Didactic can declare a generalized algebraic theory directly. The declaration
surface covers plain and indexed families, constructors with refined result
indices, dependent motives, equations, directed rewrites, and user-defined
eliminators. Compilation produces a `panproto.Theory` and runs Panproto's full
theory checker before returning it.

The same family can govern a `Model` field. This gives schema authors a direct
way to state that the type of one field depends on the value of another, while
keeping the dependency visible to validation, JSON Schema, migrations,
Pydantic, and FastAPI.

## Declare an indexed language

A declaration names its inputs as keyword arguments, in order, each with a
sort. The following language has codes for integers and booleans, a carrier
`El(t)`, and expressions indexed by their result code:

```python
import didactic.api as dx


lang = dx.GADT("TypedExpression")

Ty = lang.sort("Ty", closed=True)
El = lang.family("El", t=Ty)
Expr = lang.family("Expr", t=Ty, closed=True)

int_code = lang.constructor("int_code", returns=Ty)
bool_code = lang.constructor("bool_code", returns=Ty)

int_value = lang.operation("int_value", returns=El[int_code()])
bool_value = lang.operation("bool_value", returns=El[bool_code()])

IntLit = lang.constructor("IntLit", value=El[int_code()], returns=Expr[int_code()])
BoolLit = lang.constructor("BoolLit", value=El[bool_code()], returns=Expr[bool_code()])
```

`Ty` and `Expr(t)` are closed. Their constructor lists are therefore complete,
which lets Panproto check case coverage. `El(t)` is open because ordinary
operations may produce carrier values.

A family is applied to its indices by subscripting: `El[int_code()]` is the
sort of integer values, and `Expr[int_code()]` the sort of integer-typed
expressions. A family with no indices, such as `Ty`, is already a sort and is
passed as it is.

Every name in this declaration is a Python name. `IntLit` is the constructor
itself, and calling it builds a term: `IntLit(int_value())`. A misspelt
reference is a `NameError` on the line that contains it, and an editor can
complete, rename, and jump to any of them.

## Sorts that depend on earlier inputs

A later input's sort may mention an earlier input. Write it as a lambda whose
parameters name the inputs it needs. The lambda runs once, with a symbolic
variable for each name, and its parameter names are checked against the
inputs declared before it:

```python
Nat = lang.sort("Nat", closed=True)
A = lang.sort("A")
Vec = lang.family("Vec", n=Nat, closed=True)

zero = lang.constructor("zero", returns=Nat)
succ = lang.constructor("succ", n=Nat, returns=Nat)
nil = lang.constructor("nil", returns=Vec[zero()])
cons = lang.constructor(
    "cons",
    n=dx.Implicit(Nat),
    x=A,
    rest=lambda n: Vec[n],
    returns=lambda n: Vec[succ(n)],
)
```

`rest` has sort `Vec(n)` and the result has sort `Vec(succ(n))`, both in terms
of the first input. `dx.Implicit` marks an input Panproto infers from the
explicit ones, so callers write `cons(x, rest)` and the length is recovered by
unification.

Family indices form the same kind of telescope. A declaration such as
`Term(context, type)` can give its second index the sort `Type(context)`:

```python
Context = lang.sort("Context")
Type = lang.family("Type", context=Context)
Term = lang.family("Term", context=Context, type=lambda context: Type[context])
```

## Define an eliminator

An eliminator is an operation whose result sort is a motive that may mention
its inputs, and whose definition is a case analysis over one of them. Both are
given in the declaration. The body is a lambda over every input, in order, and
`dx.match` takes one keyword per constructor whose value is a lambda over that
constructor's binders:

```python
evaluate = lang.eliminator(
    "evaluate",
    t=Ty,
    expression=lambda t: Expr[t],
    returns=lambda t: El[t],
    body=lambda t, expression: dx.match(
        expression,
        IntLit=lambda value: value,
        BoolLit=lambda value: value,
    ),
)

theory = lang.compile()
```

The two branch bodies have sorts `El(int_code())` and `El(bool_code())`.
Panproto checks each one against the motive under that branch's constructor
refinement. A missing reachable constructor, an unreachable branch, or a
branch body at the wrong index rejects the theory.

Inside a body, `dx.match` checks its constructor names against the scrutinee's
family at once and names the valid set on a miss, and checks each branch's
binder count against its constructor. Panproto's checker remains the
authority on everything else.

A branch whose body only applies one operation may name the operation instead
of writing the lambda: `nil=fallback` reads as `nil=lambda: fallback()`, and
the binders are that operation's own input names. A body given as `...` or
omitted declares the eliminator without defining it; `Operation.define` then
supplies the body later.

`compile()` is the freeze point. It returns the same checked theory on repeated
calls and rejects later declarations. Failed compilation does not seal the
builder, which leaves the declaration available for correction.

## Construct and reduce terms

Calling an `Operation` constructs an immutable `App`. `dx.match` and `dx.let`
build case analyses and local bindings from lambdas in the same way as above,
and `dx.hole` builds a typed hole. Every term has a canonical JSON-shaped
representation:

```python
term = evaluate(int_code(), IntLit(int_value()))

assert lang.infer_sort(term) == El[int_code()]
assert lang.normalize(term) == int_value()
assert dx.term_from_spec(term.to_spec()) == term
```

Substitution through `Let` and `Case` is capture-avoiding. Case inference also
applies constructor-result refinements to branch-local binders and rejects a
result sort that would let an existential constructor index escape its branch.

`normalize()` executes definitions and directed rewrites symbolically. Its
step budget fails closed on a nonterminating rewrite system. Panproto remains
the authority for theory checking; `infer_sort()` and `normalize()` are useful
construction-time tools, not a second implementation of the GAT checker.

## Type checking the declaration

Everything above is an ordinary runtime expression, so a strict type checker
accepts it as written. The lambdas are typed as unions over arities, which
lets the checker infer each binder as a `dx.Var`; a lambda with more than
eight parameters still runs but its parameters are no longer inferred.

## Put an indexed family in a Model

`Universe` builds the common finite-code pattern. It declares a closed code
sort and an open element family, then associates each code with a Python
carrier type:

```python
from typing import Annotated, Literal


Payload = dx.Universe("Payload", text=str, number=float)


class Record(dx.Model):
    kind: Literal["text", "number"]
    body: Annotated[str | float, Payload.at("kind")]


Record(kind="text", body="hello")
Record(kind="number", body=2.5)
```

The wide annotation remains intelligible to Python type checkers. The
`IndexedBy` metadata states the stronger runtime contract. Thus
`Record(kind="number", body="hello")` raises a `ValidationError` with an
`index_mismatch` entry, and `with_()` rechecks the dependency after an immutable
update.

The generated Model theory carries `kind` and `body` in its primary sort's
dependent telescope. It does not emit them as projections, since a projection
into a closed code family would be an unlisted introduction form. Other fields
remain ordinary operations whose owner input includes the telescope.

Two universes may reuse a runtime label such as `"text"`. Their generated
constructor and injection names include the universe name, so both declarations
can coexist in one Model theory.

## Use an arbitrary family as an index

`indexed_by()` connects a user-declared family to one or more sibling fields.
Index fields may contain symbolic `Term` values. Optional `cases` associate
concrete index tuples with Python carrier types:

```python
shapes = dx.GADT("Shapes")
Dim = shapes.sort("Dim", closed=True)
Matrix = shapes.family("Matrix", rows=Dim, columns=Dim)
two = shapes.constructor("two", returns=Dim)

marker = dx.indexed_by(
    Matrix,
    "rows",
    "columns",
    cases={
        (two(), two()): tuple[tuple[float, float], tuple[float, float]],
    },
)
```

Use the marker in `Annotated[payload_type, marker]`. Model creation checks that
every named index field exists and that indexed dependencies are acyclic. The
Model theory orders dependent fields topologically, preserving declaration
order whenever no dependency forces a different order.

## Schema evolution and integrations

JSON Schema renders each known Python case as an `if` and `then` refinement.
The Pydantic adapter installs the same cross-field validator, and the FastAPI
adapter carries those conditions into OpenAPI.

Indexed contracts also enter compatibility reports. A change to the family,
its index fields, its concrete cases, or a case's Python carrier is breaking.
`synthesise_migration()` refuses that change because choosing a transport
between indices requires an explicit migration. Panproto's morphism checker
provides the lower-level guarantee: a constructor mapping whose result index
changes is ill-typed.

Inbound `model_from_spec()` synthesis rejects a parameterized primary sort.
The Theory preserves its dependent telescope, but it does not contain the
Python carrier annotations needed to reconstruct `IndexedBy` runtime
validation. Failing at that boundary avoids producing a Model with weaker
invariants than the source declaration.

Panproto GAT signatures are first-order. They do not quantify over sorts, so a
polymorphic type former is encoded with a Tarski universe: codes are terms in a
plain sort and decoding is an indexed family such as `El(code)`. Closed
families admit exhaustive case analysis, while open families admit arbitrary
operations that produce them. Choose the closure from the introductions the
language needs.
