"""Tagged-union values held in containers build, read and dump in linear time.

A stored tagged-union value is the variant's wire JSON. A field holds one
directly (``left: Expr``) or inside a container (``tuple[Expr, ...]``,
``Expr | None``, ``dict[str, Expr]``, ``frozenset[Expr]``, nestings of
these, a bare Model that holds one of them, a Model-ref recursive alias).
For every shape:

- building a tree constructs exactly the Models the caller constructs;
- reading a child out of a stored value constructs no Model;
- dumping a tree constructs no Model;
- validating a dumped tree constructs each node once.

``Model.__init__`` calls are counted rather than time measured, so the
bounds are deterministic. The second half pins the observable output
of every shape (``model_dump``, ``model_dump_json``, stored text, reads,
both validation paths and their error locations) to literal values.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Literal

import pytest

import didactic.api as dx
from didactic.models._model import Model

if TYPE_CHECKING:
    from didactic.types._typing import FieldValue, JsonValue


class Expr(dx.TaggedUnion, discriminator="kind"):
    """An expression tree."""


class Other(dx.TaggedUnion, discriminator="kind"):
    """A second root sharing the discriminator."""


class Lit(Expr):
    value: float
    kind: Literal["lit"] = "lit"


class Odd(Other):
    n: int
    kind: Literal["odd"] = "odd"


class Call(Expr):
    func: str
    args: tuple[Expr, ...]
    kind: Literal["call"] = "call"


class Maybe(Expr):
    child: Expr | None = None
    kind: Literal["maybe"] = "maybe"


class Table(Expr):
    entries: dict[str, Expr]
    kind: Literal["table"] = "table"


class Grid(Expr):
    rows: tuple[tuple[Expr | None, ...], ...]
    kind: Literal["grid"] = "grid"


class Bag(Expr):
    members: frozenset[Expr]
    kind: Literal["bag"] = "bag"


class Box(dx.Model):
    items: dict[str, tuple[Expr, ...]]


class Boxed(Expr):
    box: Box
    kind: Literal["boxed"] = "boxed"


class Mixed(Expr):
    both: tuple[Expr | Other, ...]
    kind: Literal["mixed"] = "mixed"


type Ast = int | Call | tuple["Ast", ...]


class Quote(Expr):
    body: Ast
    kind: Literal["quote"] = "quote"


class Add(Expr):
    left: Expr
    right: Expr
    kind: Literal["add"] = "add"


class Tagged(Expr):
    """A variant whose ``after`` validator is not idempotent."""

    name: str
    kind: Literal["tagged"] = "tagged"

    @dx.validates("name", mode="after")
    def _mark(self, value: str) -> str:
        return value + "!"


class Holder(dx.Model):
    one: Expr
    many: tuple[Expr, ...]


# -- counting -------------------------------------------------------------


@pytest.fixture
def inits(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    """Count ``Model.__init__`` calls; reset by assigning ``inits[0] = 0``."""
    counter = [0]
    original_init = Model.__init__

    def counting_init(self: Model, **kwargs: FieldValue | JsonValue) -> None:
        counter[0] += 1
        original_init(self, **kwargs)

    monkeypatch.setattr(Model, "__init__", counting_init)
    yield counter


def _lit(i: int) -> Lit:
    return Lit(value=float(i))


# each shape wraps ``node`` in one level (``i`` numbers the level's sibling
# leaf) and says how many Models a level constructs
type Wrap = Callable[[Expr, int], Expr]


def _is_spine(node: Expr | Other) -> bool:
    # every level's sibling leaf is a ``Lit`` with a positive value
    return not (isinstance(node, Lit) and node.value > 0)


def _head(node: Expr) -> Expr | None:
    """Return the child a shape threads its chain through; ``None`` at the seed."""
    child: Expr | Other | Ast | None = None
    match node:
        case Call(args=(child, *_)) | Mixed(both=(child, *_)) | Add(left=child):
            pass
        case Maybe(child=child) | Table(entries={"spine": child}):
            pass
        case Grid(rows=(_, (child, *_))) | Boxed(box=Box(items={"spine": (child,)})):
            pass
        case Quote(body=(Call(args=(child,)), _)):
            pass
        case Bag(members=members):
            child = next(m for m in members if _is_spine(m))
        case _:
            child = None
    assert child is None or isinstance(child, Expr)
    return child


SHAPES: dict[str, tuple[Wrap, int]] = {
    "tuple": (lambda node, i: Call(func="f", args=(node, _lit(i))), 2),
    "optional": (lambda node, i: Maybe(child=node), 1),
    "dict": (lambda node, i: Table(entries={"spine": node, "leaf": _lit(i)}), 2),
    "nested": (lambda node, i: Grid(rows=((_lit(i), None), (node,))), 2),
    "frozenset": (lambda node, i: Bag(members=frozenset({node, _lit(i)})), 2),
    "model": (
        lambda node, i: Boxed(box=Box(items={"spine": (node,), "leaf": (_lit(i),)})),
        3,
    ),
    "roots": (lambda node, i: Mixed(both=(node, Odd(n=i))), 2),
    "alias": (lambda node, i: Quote(body=(Call(func="q", args=(node,)), i)), 2),
    "field": (lambda node, i: Add(left=node, right=_lit(i)), 2),
}


def _build(shape: str, depth: int) -> Expr:
    wrap, _ = SHAPES[shape]
    node: Expr = Lit(value=0.0)
    for i in range(depth):
        node = wrap(node, i + 1)
    return node


@pytest.mark.parametrize("shape", sorted(SHAPES))
@pytest.mark.parametrize("depth", [4, 8, 16, 32])
def test_building_constructs_only_the_callers_models(
    inits: list[int], shape: str, depth: int
) -> None:
    _, per_level = SHAPES[shape]
    inits[0] = 0
    _build(shape, depth)
    assert inits[0] == 1 + per_level * depth


@pytest.mark.parametrize("shape", sorted(SHAPES))
@pytest.mark.parametrize("depth", [4, 8, 16, 32])
def test_reading_the_spine_constructs_no_model(
    inits: list[int], shape: str, depth: int
) -> None:
    node: Expr | None = _build(shape, depth)
    inits[0] = 0
    visited = 0
    while node is not None:
        visited += 1
        node = _head(node)
    assert visited == depth + 1
    assert inits[0] == 0


@pytest.mark.parametrize("shape", sorted(SHAPES))
@pytest.mark.parametrize("depth", [4, 8, 16, 32])
def test_dumping_constructs_no_model_and_validating_constructs_each_node_once(
    inits: list[int], shape: str, depth: int
) -> None:
    _, per_level = SHAPES[shape]
    tree = _build(shape, depth)
    inits[0] = 0
    wire = tree.model_dump_json()
    tree.model_dump()
    assert inits[0] == 0
    back = type(tree).model_validate_json(wire)
    assert inits[0] == 1 + per_level * depth
    assert back == tree
    assert back.model_dump_json() == wire


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_wire_dict_rebuilds_an_equal_value_without_constructing(
    inits: list[int], shape: str
) -> None:
    tree = _build(shape, 8)
    wire = tree.to_wire_dict()
    assert wire == json.loads(tree.model_dump_json())
    inits[0] = 0
    rebuilt = type(tree).from_wire_dict(wire)
    assert inits[0] == 0
    assert rebuilt == tree
    assert rebuilt.to_storage_dict() == tree.to_storage_dict()


def test_reading_a_stored_union_value_returns_it_as_validated() -> None:
    """A stored variant is rebuilt as stored, so validators do not run twice."""
    holder = Holder(one=Tagged(name="x"), many=(Tagged(name="y"),))
    assert Tagged(name="x").to_storage_dict()["name"] == "x!"
    one, (first,) = holder.one, holder.many
    assert isinstance(one, Tagged)
    assert isinstance(first, Tagged)
    assert (one.name, first.name) == ("x!", "y!")
    assert holder.model_dump_json() == (
        '{"one": {"name": "x!", "kind": "tagged"}, '
        '"many": [{"name": "y!", "kind": "tagged"}]}'
    )


# -- observable output, pinned --------------------------------------------

ONE = Lit(value=1.0)
TWO = Lit(value=2.5)

SAMPLES: dict[str, Expr] = {
    "tuple": Call(func="f", args=(ONE, Call(func="g", args=(TWO,)))),
    "optional": Maybe(child=Maybe(child=ONE)),
    "optional_none": Maybe(),
    "dict": Table(entries={"a": ONE, "b": Table(entries={"c": TWO})}),
    "nested": Grid(rows=((ONE, None), (), (Grid(rows=((TWO,),)),))),
    "frozenset": Bag(members=frozenset({ONE, TWO, Bag(members=frozenset({ONE}))})),
    "model": Boxed(box=Box(items={"k": (ONE, Boxed(box=Box(items={})))})),
    "roots": Mixed(both=(ONE, Odd(n=3), Mixed(both=()))),
    "alias": Quote(body=(1, Call(func="g", args=(Quote(body=(2, ())),)))),
    "field": Add(left=Add(left=ONE, right=TWO), right=ONE),
}

DUMP_JSON: dict[str, str] = {
    "tuple": (
        '{"func": "f", "args": [{"value": 1.0, "kind": "lit"}, {"func": "g", "a'
        'rgs": [{"value": 2.5, "kind": "lit"}], "kind": "call"}], "kind": "call'
        '"}'
    ),
    "optional": (
        '{"child": {"child": {"value": 1.0, "kind": "lit"}, "kind": "maybe"}, "'
        'kind": "maybe"}'
    ),
    "optional_none": '{"child": null, "kind": "maybe"}',
    "dict": (
        '{"entries": {"a": {"value": 1.0, "kind": "lit"}, "b": {"entries": {"c"'
        ': {"value": 2.5, "kind": "lit"}}, "kind": "table"}}, "kind": "table"}'
    ),
    "nested": (
        '{"rows": [[{"value": 1.0, "kind": "lit"}, null], [], [{"rows": [[{"val'
        'ue": 2.5, "kind": "lit"}]], "kind": "grid"}]], "kind": "grid"}'
    ),
    "frozenset": (
        '{"members": [{"members": [{"value": 1.0, "kind": "lit"}], "kind": "bag'
        '"}, {"value": 1.0, "kind": "lit"}, {"value": 2.5, "kind": "lit"}], "ki'
        'nd": "bag"}'
    ),
    "model": (
        '{"box": {"items": {"k": [{"value": 1.0, "kind": "lit"}, {"box": {"item'
        's": {}}, "kind": "boxed"}]}}, "kind": "boxed"}'
    ),
    "roots": (
        '{"both": [{"value": 1.0, "kind": "lit"}, {"n": 3, "kind": "odd"}, {"bo'
        'th": [], "kind": "mixed"}], "kind": "mixed"}'
    ),
    "alias": (
        '{"body": {"Ast_tuple": [{"Ast_int": 1}, {"Ast_call": {"func": "g", "ar'
        'gs": [{"body": {"Ast_tuple": [{"Ast_int": 2}, {"Ast_tuple": []}]}, "ki'
        'nd": "quote"}], "kind": "call"}}]}, "kind": "quote"}'
    ),
    "field": (
        '{"left": {"left": {"value": 1.0, "kind": "lit"}, "right": {"value": 2.'
        '5, "kind": "lit"}, "kind": "add"}, "right": {"value": 1.0, "kind": "li'
        't"}, "kind": "add"}'
    ),
}
STORAGE: dict[str, dict[str, str]] = {
    "tuple": {
        "func": "f",
        "args": (
            '["{\\"value\\": 1.0, \\"kind\\": \\"lit\\"}", "{\\"func\\": \\"g\\", '
            '\\"args\\": [{\\"value\\": 2.5, \\"kind\\": \\"lit\\"}], \\"kind\\": '
            '\\"call\\"}"]'
        ),
        "kind": "call",
    },
    "optional": {
        "child": '{"child": {"value": 1.0, "kind": "lit"}, "kind": "maybe"}',
        "kind": "maybe",
    },
    "optional_none": {
        "child": "null",
        "kind": "maybe",
    },
    "dict": {
        "entries": (
            '{"a": "{\\"value\\": 1.0, \\"kind\\": \\"lit\\"}", "b": "{\\"entries\\'
            '": {\\"c\\": {\\"value\\": 2.5, \\"kind\\": \\"lit\\"}}, \\"kind\\": '
            '\\"table\\"}"}'
        ),
        "kind": "table",
    },
    "nested": {
        "rows": (
            '["[\\"{\\\\\\"value\\\\\\": 1.0, \\\\\\"kind\\\\\\": \\\\\\"lit\\\\\\"'
            '}\\", \\"null\\"]", "[]", "[\\"{\\\\\\"rows\\\\\\": [[{\\\\\\"value\\'
            '\\\\": 2.5, \\\\\\"kind\\\\\\": \\\\\\"lit\\\\\\"}]], \\\\\\"kind\\\\'
            '\\": \\\\\\"grid\\\\\\"}\\"]"]'
        ),
        "kind": "grid",
    },
    "frozenset": {
        "members": (
            '["{\\"members\\": [{\\"value\\": 1.0, \\"kind\\": \\"lit\\"}], \\"kind'
            '\\": \\"bag\\"}", "{\\"value\\": 1.0, \\"kind\\": \\"lit\\"}", "{\\"va'
            'lue\\": 2.5, \\"kind\\": \\"lit\\"}"]'
        ),
        "kind": "bag",
    },
    "model": {
        "box": (
            '{"items": "{\\"k\\": \\"[\\\\\\"{\\\\\\\\\\\\\\"value\\\\\\\\\\\\\\": '
            '1.0, \\\\\\\\\\\\\\"kind\\\\\\\\\\\\\\": \\\\\\\\\\\\\\"lit\\\\\\\\\\'
            '\\\\"}\\\\\\", \\\\\\"{\\\\\\\\\\\\\\"box\\\\\\\\\\\\\\": {\\\\\\\\\\'
            '\\\\"items\\\\\\\\\\\\\\": {}}, \\\\\\\\\\\\\\"kind\\\\\\\\\\\\\\": \\'
            '\\\\\\\\\\\\"boxed\\\\\\\\\\\\\\"}\\\\\\"]\\"}"}'
        ),
        "kind": "boxed",
    },
    "roots": {
        "both": (
            '["{\\"value\\": 1.0, \\"kind\\": \\"lit\\"}", "{\\"n\\": 3, \\"kind\\"'
            ': \\"odd\\"}", "{\\"both\\": [], \\"kind\\": \\"mixed\\"}"]'
        ),
        "kind": "mixed",
    },
    "alias": {
        "body": (
            '{"Ast_tuple": [{"Ast_int": 1}, {"Ast_call": {"func": "g", "args": [{"b'
            'ody": {"Ast_tuple": [{"Ast_int": 2}, {"Ast_tuple": []}]}, "kind": "quo'
            'te"}], "kind": "call"}}]}'
        ),
        "kind": "quote",
    },
    "field": {
        "left": (
            '{"left": {"value": 1.0, "kind": "lit"}, "right": {"value": 2.5, "kind"'
            ': "lit"}, "kind": "add"}'
        ),
        "right": '{"value": 1.0, "kind": "lit"}',
        "kind": "add",
    },
}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_dump_json_and_storage_are_pinned(name: str) -> None:
    sample = SAMPLES[name]
    assert sample.model_dump_json() == DUMP_JSON[name]
    assert sample.model_dump_json(by_alias=True) == DUMP_JSON[name]
    assert sample.to_storage_dict() == STORAGE[name]


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_validating_the_pinned_dump_restores_the_value(name: str) -> None:
    sample = SAMPLES[name]
    back = type(sample).model_validate_json(DUMP_JSON[name])
    assert back == sample
    assert back.to_storage_dict() == STORAGE[name]


@pytest.mark.parametrize("name", sorted(set(SAMPLES) - {"alias", "model"}))
def test_validating_model_dump_restores_the_value(name: str) -> None:
    sample = SAMPLES[name]
    assert type(sample).model_validate(sample.model_dump()) == sample


def test_model_dump_keeps_decoded_values_in_containers() -> None:
    assert SAMPLES["tuple"].model_dump() == {
        "func": "f",
        "args": (ONE, Call(func="g", args=(TWO,))),
        "kind": "call",
    }
    assert SAMPLES["dict"].model_dump() == {
        "entries": {"a": ONE, "b": Table(entries={"c": TWO})},
        "kind": "table",
    }
    assert SAMPLES["nested"].model_dump() == {
        "rows": ((ONE, None), (), (Grid(rows=((TWO,),)),)),
        "kind": "grid",
    }
    assert SAMPLES["frozenset"].model_dump() == {
        "members": frozenset({ONE, TWO, Bag(members=frozenset({ONE}))}),
        "kind": "bag",
    }
    assert SAMPLES["roots"].model_dump() == {
        "both": (ONE, Odd(n=3), Mixed(both=())),
        "kind": "mixed",
    }
    # a sum-sort field dumps its stored wire JSON parsed
    assert SAMPLES["optional"].model_dump() == {
        "child": {"child": {"value": 1.0, "kind": "lit"}, "kind": "maybe"},
        "kind": "maybe",
    }
    assert SAMPLES["field"].model_dump() == {
        "left": {
            "left": {"value": 1.0, "kind": "lit"},
            "right": {"value": 2.5, "kind": "lit"},
            "kind": "add",
        },
        "right": {"value": 1.0, "kind": "lit"},
        "kind": "add",
    }
    assert SAMPLES["alias"].model_dump() == {
        "body": {
            "Ast_tuple": [
                {"Ast_int": 1},
                {
                    "Ast_call": {
                        "func": "g",
                        "args": [
                            {
                                "body": {
                                    "Ast_tuple": [{"Ast_int": 2}, {"Ast_tuple": []}]
                                },
                                "kind": "quote",
                            }
                        ],
                        "kind": "call",
                    }
                },
            ]
        },
        "kind": "quote",
    }


def test_reads_return_the_stored_values() -> None:
    call = SAMPLES["tuple"]
    assert isinstance(call, Call)
    assert call.args == (ONE, Call(func="g", args=(TWO,)))
    table = SAMPLES["dict"]
    assert isinstance(table, Table)
    assert table.entries == {"a": ONE, "b": Table(entries={"c": TWO})}
    grid = SAMPLES["nested"]
    assert isinstance(grid, Grid)
    assert grid.rows == ((ONE, None), (), (Grid(rows=((TWO,),)),))
    maybe = SAMPLES["optional"]
    assert isinstance(maybe, Maybe)
    assert maybe.child == Maybe(child=ONE)
    assert Maybe().child is None
    boxed = SAMPLES["model"]
    assert isinstance(boxed, Boxed)
    assert boxed.box == Box(items={"k": (ONE, Boxed(box=Box(items={})))})
    quote = SAMPLES["alias"]
    assert isinstance(quote, Quote)
    assert quote.body == (1, Call(func="g", args=(Quote(body=(2, ())),)))


# -- invalid elements are still rejected where they sit --------------------

type Entry = tuple[tuple[str | int, ...], str, str]

INVALID: dict[str, tuple[type[Model], JsonValue, list[Entry]]] = {
    "tuple": (
        Call,
        {
            "func": "f",
            "args": [{"kind": "lit", "value": 1.0}, {"kind": "lit", "value": "x"}],
        },
        [(("args", 1, "value"), "type_error", "expected float, got str")],
    ),
    "tuple_nested": (
        Call,
        {
            "func": "f",
            "args": [{"kind": "call", "func": "g", "args": [{"kind": "lit"}]}],
        },
        [
            (
                ("args", 0, "args", 0, "value"),
                "missing_required",
                "required field 'value' not supplied",
            )
        ],
    ),
    "tuple_unknown_tag": (
        Call,
        {"func": "f", "args": [{"kind": "nope"}]},
        [
            (
                ("args",),
                "type_error",
                "TaggedUnion 'Expr' has no variant registered for kind='nope'; "
                "expected one of ['add', 'bag', 'boxed', 'call', 'grid', 'holds', "
                "'lit', 'maybe', 'mixed', 'needs', 'quote', 'table', 'tagged'].",
            )
        ],
    ),
    "dict": (
        Table,
        {
            "entries": {
                "a": {"kind": "lit", "value": 1.0},
                "b": {"kind": "lit", "value": []},
            }
        },
        [(("entries", "b", "value"), "type_error", "expected a JSON scalar, got list")],
    ),
    "optional": (
        Maybe,
        {"child": {"kind": "maybe", "child": {"kind": "lit", "value": "q"}}},
        [(("child", "child", "value"), "type_error", "expected float, got str")],
    ),
    "nested": (
        Grid,
        {"rows": [[None, {"kind": "lit", "value": "z"}]]},
        [(("rows", 0, 1, "value"), "type_error", "expected float, got str")],
    ),
    "frozenset": (
        Bag,
        {"members": [{"kind": "lit", "value": "z"}]},
        [(("members", "value"), "type_error", "expected float, got str")],
    ),
    "model": (
        Boxed,
        {
            "box": {
                "items": {
                    "k": [{"kind": "lit", "value": 1.0}, {"kind": "lit", "value": "z"}]
                }
            }
        },
        [(("box", "items", "k", 1, "value"), "type_error", "expected float, got str")],
    ),
    "roots": (
        Mixed,
        {"both": [{"kind": "lit", "value": 1.0}, {"kind": "odd", "n": "x"}]},
        [(("both", 1, "n"), "type_error", "expected int, got str")],
    ),
    "field": (
        Add,
        {
            "left": {
                "kind": "add",
                "left": {"kind": "lit", "value": "v"},
                "right": {"kind": "lit", "value": 1.0},
            },
            "right": {"kind": "lit", "value": 2.0},
        },
        [(("left", "left", "value"), "type_error", "expected float, got str")],
    ),
}


@pytest.mark.parametrize("name", sorted(INVALID))
@pytest.mark.parametrize("path", ["model_validate", "model_validate_json"])
def test_invalid_elements_are_rejected_at_their_location(name: str, path: str) -> None:
    cls, payload, expected = INVALID[name]
    assert isinstance(payload, dict)
    with pytest.raises(dx.ValidationError) as info:
        if path == "model_validate":
            cls.model_validate(payload)
        else:
            cls.model_validate_json(json.dumps(payload))
    assert info.value.model is cls
    assert [(e.loc, e.type, e.msg) for e in info.value.entries] == expected


def test_invalid_alias_payload_is_rejected_at_its_location() -> None:
    payload = {
        "body": {"Ast_call": {"func": "g", "args": [{"kind": "lit", "value": "x"}]}}
    }
    with pytest.raises(dx.ValidationError) as info:
        Quote.model_validate_json(json.dumps(payload))
    assert info.value.model is Quote
    assert [(e.loc, e.type, e.msg) for e in info.value.entries] == [
        (("body", "args", 0, "value"), "type_error", "expected float, got str")
    ]


def test_constructing_with_a_non_variant_element_is_rejected() -> None:
    with pytest.raises(dx.ValidationError) as info:
        Call(func="f", args=(ONE, "nope"))  # type: ignore[arg-type]
    assert [(e.loc, e.type) for e in info.value.entries] == [(("args",), "type_error")]
    assert info.value.entries[0].msg.startswith(
        "value of type str is not a registered variant of TaggedUnion 'Expr'"
    )


# -- opaque fields and incomplete wire dicts -------------------------------


class Handle:
    """A value with no wire form."""


class Holds(Expr):
    handle: Handle = dx.field(default_factory=Handle, opaque=True)
    kind: Literal["holds"] = "holds"


class Needs(Expr):
    handle: Handle = dx.field(opaque=True)
    kind: Literal["needs"] = "needs"


def test_a_read_variant_takes_its_opaque_fields_default() -> None:
    original = Handle()
    call = Call(func="f", args=(Holds(handle=original),))
    (child,) = call.args
    assert isinstance(child, Holds)
    assert isinstance(child.handle, Handle)
    assert child.handle is not original
    assert child.to_storage_dict() == {"handle": "null", "kind": "holds"}


def test_a_read_variant_without_an_opaque_default_is_refused() -> None:
    call = Call(func="f", args=(Needs(handle=Handle()),))
    with pytest.raises(dx.ValidationError) as info:
        call.args  # noqa: B018
    assert info.value.model is Needs
    assert [(e.loc, e.type, e.msg) for e in info.value.entries] == [
        (("handle",), "missing_required", "required field 'handle' not supplied")
    ]


def test_a_wire_dict_missing_a_field_is_refused() -> None:
    with pytest.raises(ValueError, match="lacks field 'func'"):
        Call.from_wire_dict({"args": [], "kind": "call"})
