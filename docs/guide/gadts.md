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

The following language has codes for integers and booleans, a carrier
`El(t)`, and expressions indexed by their result code:

```python
import didactic.api as dx


language = dx.GADT("TypedExpression")

ty = language.sort("Ty", closed=True)
el = language.family("El", parameters=(dx.param("t", ty()),))
expr = language.family(
    "Expr",
    parameters=(dx.param("t", ty()),),
    closed=True,
)

int_code = language.constructor("int_code", result=ty())
bool_code = language.constructor("bool_code", result=ty())

int_value = language.operation("int_value", result=el(int_code()))
bool_value = language.operation("bool_value", result=el(bool_code()))

int_lit = language.constructor(
    "IntLit",
    inputs=(dx.param("value", el(int_code())),),
    result=expr(int_code()),
)
bool_lit = language.constructor(
    "BoolLit",
    inputs=(dx.param("value", el(bool_code())),),
    result=expr(bool_code()),
)
```

`Ty` and `Expr(t)` are closed. Their constructor lists are therefore complete,
which lets Panproto check case coverage. `El(t)` is open because ordinary
operations may produce carrier values.

Family arguments are terms. A family may have any finite dependent telescope,
so a declaration such as `Term(context, type)` can give its second parameter
the sort `Type(context)`. A two-dimensional family is equally direct:

```python
matrix = language.family(
    "Matrix",
    parameters=(
        dx.param("rows", ty()),
        dx.param("columns", ty()),
    ),
)
```

## Define a motive and eliminator

An eliminator is an operation with a named motive. Here the result sort is
`El(t)`, so each constructor branch refines the same motive at a different
index:

```python
evaluate = language.eliminator(
    "evaluate",
    inputs=(
        dx.param("t", ty()),
        dx.param("expression", expr(dx.var("t"))),
    ),
    motive=el(dx.var("t")),
)

evaluate.define(
    dx.case(
        dx.var("expression"),
        dx.branch("IntLit", "value", body=dx.var("value")),
        dx.branch("BoolLit", "value", body=dx.var("value")),
    )
)

theory = language.compile()
```

The two branch bodies have sorts `El(int_code())` and `El(bool_code())`.
Panproto checks each one against the motive under that branch's constructor
refinement. A missing reachable constructor, an unreachable branch, or a
branch body at the wrong index rejects the theory.

`compile()` is the freeze point. It returns the same checked theory on repeated
calls and rejects later declarations. Failed compilation does not seal the
builder, which leaves the declaration available for correction.

## Construct and reduce terms

Calling an `Operation` constructs an immutable `App`. The helpers `var`,
`app`, `hole`, `let`, `branch`, and `case` cover Panproto's complete term AST.
Every term has a canonical JSON-shaped representation:

```python
term = evaluate(int_code(), int_lit(int_value()))

assert language.infer_sort(term) == el(int_code())
assert language.normalize(term) == int_value()
assert dx.term_from_spec(term.to_spec()) == term
```

Substitution through `Let` and `Case` is capture-avoiding. Case inference also
applies constructor-result refinements to branch-local binders and rejects a
result sort that would let an existential constructor index escape its branch.

`normalize()` executes definitions and directed rewrites symbolically. Its
step budget fails closed on a nonterminating rewrite system. Panproto remains
the authority for theory checking; `infer_sort()` and `normalize()` are useful
construction-time tools, not a second implementation of the GAT checker.

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
marker = dx.indexed_by(
    matrix,
    "rows",
    "columns",
    cases={
        (int_code(), int_code()): tuple[float, ...],
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
