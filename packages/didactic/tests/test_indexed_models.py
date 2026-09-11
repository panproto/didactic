"""Indexed-family fields across validation, transport, theories, and schemas."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Literal, cast

import panproto
import pytest
from hypothesis import given
from hypothesis import strategies as st

import didactic.api as dx
from didactic.migrations._fingerprint import structural_fingerprint
from didactic.theory._theory import build_theory_spec

if TYPE_CHECKING:
    from didactic.types._typing import JsonValue


PAYLOAD = dx.Universe("PayloadTest", text=str, number=float)


class IndexedRecord(dx.Model):
    """A payload whose Python and GAT sorts are selected by ``kind``."""

    kind: Literal["text", "number"]
    body: Annotated[str | float, PAYLOAD.at("kind")]
    label: str = ""


FIRST_PAYLOAD = dx.Universe("FirstPayload", text=str, number=float)
SECOND_PAYLOAD = dx.Universe("SecondPayload", text=str, flag=bool)


class PairOfPayloads(dx.Model):
    first_kind: Literal["text", "number"]
    first_body: Annotated[str | float, FIRST_PAYLOAD.at("first_kind")]
    second_kind: Literal["text", "flag"]
    second_body: Annotated[str | bool, SECOND_PAYLOAD.at("second_kind")]


def _expression_language() -> tuple[
    dx.GADT,
    dx.Family,
    dx.Family,
    dx.Operation,
    dx.Operation,
    dx.Operation,
    dx.Operation,
    dx.Operation,
]:
    theory = dx.GADT("ModelExpression")
    ty = theory.sort("ModelTy", closed=True)
    expr = theory.family("ModelExpr", parameters=(dx.param("t", ty()),), closed=True)
    integer = theory.constructor("model_int", result=ty())
    boolean = theory.constructor("model_bool", result=ty())
    int_atom = theory.sort("ModelIntAtom")
    make_int = theory.operation("make_model_int", result=int_atom())
    int_lit = theory.constructor(
        "ModelIntLit",
        inputs=(dx.param("value", int_atom()),),
        result=expr(integer()),
    )
    bool_lit = theory.constructor(
        "ModelBoolLit",
        inputs=(dx.param("value", int_atom()),),
        result=expr(boolean()),
    )
    return theory, ty, expr, integer, boolean, make_int, int_lit, bool_lit


(
    EXPRESSION_THEORY,
    _,
    EXPRESSION_FAMILY,
    INTEGER_CODE,
    BOOLEAN_CODE,
    MAKE_INTEGER,
    INTEGER_LITERAL,
    BOOLEAN_LITERAL,
) = _expression_language()


class ExpressionBox(dx.Model):
    """A symbolic expression whose family index is stored alongside it."""

    code: dx.Term
    expression: Annotated[dx.Term, dx.indexed_by(EXPRESSION_FAMILY, "code")]


def test_valid_python_payloads_follow_their_code() -> None:
    assert IndexedRecord(kind="text", body="hello").body == "hello"
    assert IndexedRecord(kind="number", body=1.5).body == 1.5


@pytest.mark.parametrize(
    ("kind", "body"),
    [("text", 1.5), ("number", "not a number")],
)
def test_mismatched_python_payload_has_exact_index_error(
    kind: Literal["text", "number"], body: str | float
) -> None:
    with pytest.raises(dx.ValidationError) as caught:
        IndexedRecord(kind=kind, body=body)
    assert caught.value.entries == (
        dx.ValidationErrorEntry(
            loc=("body",),
            type="index_mismatch",
            msg=(
                f"value {body!r} does not inhabit the Python payload type "
                f"selected by PayloadTestEl(PayloadTest_{kind}())"
            ),
        ),
    )


def test_immutable_update_rechecks_dependency() -> None:
    record = IndexedRecord(kind="text", body="hello")
    with pytest.raises(dx.ValidationError) as caught:
        record.with_(kind="number")
    assert caught.value.entries[0].loc == ("body",)
    assert caught.value.entries[0].type == "index_mismatch"

    updated = record.with_(kind="number", body=2.5)
    assert updated == IndexedRecord(kind="number", body=2.5)


def test_indexed_python_payload_json_round_trip() -> None:
    record = IndexedRecord(kind="number", body=2.5, label="measurement")
    assert IndexedRecord.model_validate_json(record.model_dump_json()) == record


def test_model_sort_carries_dependency_as_a_telescope() -> None:
    spec = build_theory_spec(IndexedRecord)
    primary = spec["sorts"][0]
    assert primary == {
        "name": "IndexedRecord",
        "params": [
            {"name": "kind", "sort": "PayloadTestCode"},
            {
                "name": "body",
                "sort": {
                    "name": "PayloadTestEl",
                    "args": [{"Var": "kind"}],
                },
            },
        ],
        "kind": "Structural",
        "closure": "Open",
    }

    # Index and payload are parameters, not illegal projections into closed
    # families. Ordinary fields remain projections from the indexed owner.
    operations = {cast("str", item["name"]): item for item in spec["ops"]}
    assert "kind" not in operations
    assert "body" not in operations
    assert operations["label"]["inputs"] == [
        ["kind", "PayloadTestCode", "Yes"],
        [
            "body",
            {"name": "PayloadTestEl", "args": [{"Var": "kind"}]},
            "Yes",
        ],
        [
            "self",
            {
                "name": "IndexedRecord",
                "args": [{"Var": "kind"}, {"Var": "body"}],
            },
            "No",
        ],
    ]
    panproto.typecheck_theory(IndexedRecord.__theory__)


def test_symbolic_closed_family_field_is_checked_at_its_index() -> None:
    value = ExpressionBox(
        code=INTEGER_CODE(), expression=INTEGER_LITERAL(MAKE_INTEGER())
    )
    assert value.expression == INTEGER_LITERAL(MAKE_INTEGER())
    assert ExpressionBox.model_validate_json(value.model_dump_json()) == value
    panproto.typecheck_theory(ExpressionBox.__theory__)

    with pytest.raises(dx.ValidationError, match="expected ModelExpr\\(model_int"):
        ExpressionBox(code=INTEGER_CODE(), expression=BOOLEAN_LITERAL(MAKE_INTEGER()))

    with pytest.raises(dx.ValidationError, match="expects sort ModelTy"):
        ExpressionBox(code=MAKE_INTEGER(), expression=INTEGER_LITERAL(MAKE_INTEGER()))

    # The boolean code remains distinct even though both values are represented
    # by the same transport-level Term type.
    assert EXPRESSION_FAMILY(INTEGER_CODE()) != EXPRESSION_FAMILY(BOOLEAN_CODE())
    assert EXPRESSION_THEORY.infer_sort(
        BOOLEAN_LITERAL(MAKE_INTEGER())
    ) == EXPRESSION_FAMILY(BOOLEAN_CODE())


def test_term_field_uses_lossless_canonical_json_ast() -> None:
    theory, _, _, integer, _, make_int, int_lit, _ = _expression_language()

    class TermHolder(dx.Model):
        term: dx.Term

    value = TermHolder(term=int_lit(make_int()))
    raw = json.loads(value.model_dump_json())
    assert raw == {
        "term": {
            "App": {
                "op": "ModelIntLit",
                "args": [{"App": {"op": "make_model_int", "args": []}}],
            }
        }
    }
    assert TermHolder.model_validate_json(value.model_dump_json()) == value
    assert theory.infer_sort(value.term) == next(
        family(integer()) for family in theory.families if family.name == "ModelExpr"
    )


def test_json_schema_preserves_the_dependent_cases() -> None:
    schema = IndexedRecord.model_json_schema()
    assert schema["properties"]["body"] == {
        "anyOf": [{"type": "string"}, {"type": "number"}]
    }
    assert schema.get("allOf") == [
        {
            "if": {
                "properties": {"kind": {"const": "text"}},
                "required": ["kind"],
            },
            "then": {"properties": {"body": {"type": "string"}}},
        },
        {
            "if": {
                "properties": {"kind": {"const": "number"}},
                "required": ["kind"],
            },
            "then": {"properties": {"body": {"type": "number"}}},
        },
    ]


def test_indexed_fingerprint_is_stable_and_nonindexed_shape_is_unchanged() -> None:
    first = structural_fingerprint(build_theory_spec(IndexedRecord))
    second = structural_fingerprint(build_theory_spec(IndexedRecord))
    assert first == second

    class Plain(dx.Model):
        value: str

    assert build_theory_spec(Plain) == {
        "name": "Plain",
        "extends": [],
        "sorts": [
            {
                "name": "Plain",
                "params": [],
                "kind": "Structural",
                "closure": "Open",
            },
            {
                "name": "Plain_value",
                "params": [],
                "kind": {"Val": "Str"},
                "closure": "Open",
            },
        ],
        "ops": [
            {
                "name": "value",
                "inputs": [["self", "Plain", "No"]],
                "output": "Plain_value",
            }
        ],
        "eqs": [],
        "directed_eqs": [],
        "policies": [],
    }


def test_inbound_model_synthesis_fails_closed_for_indexed_spec() -> None:
    with pytest.raises(NotImplementedError, match="Python carrier annotations"):
        dx.model_from_spec(build_theory_spec(IndexedRecord))


def test_missing_index_reference_fails_at_class_definition() -> None:
    with pytest.raises(dx.GADTDeclarationError, match="missing fields: 'missing'"):

        class Broken(dx.Model):
            body: Annotated[str | float, PAYLOAD.at("missing")]

        assert Broken.__name__


@given(st.one_of(st.text(), st.floats(allow_nan=False, allow_infinity=False)))
def test_indexed_round_trip_property(value: str | float) -> None:
    """Every valid refined payload survives JSON transport."""
    kind: Literal["text", "number"] = "text" if isinstance(value, str) else "number"
    record = IndexedRecord(kind=kind, body=value)
    assert IndexedRecord.model_validate_json(record.model_dump_json()) == record


def test_json_schema_document_is_json_serializable() -> None:
    rendered = json.dumps(cast("JsonValue", IndexedRecord.model_json_schema()))
    assert "PayloadTest" not in rendered


def test_independent_universes_can_reuse_runtime_case_labels() -> None:
    value = PairOfPayloads(
        first_kind="text",
        first_body="left",
        second_kind="text",
        second_body="right",
    )
    assert value.second_body == "right"
    panproto.typecheck_theory(PairOfPayloads.__theory__)
    operations = {
        cast("str", item["name"]) for item in build_theory_spec(PairOfPayloads)["ops"]
    }
    assert {"FirstPayload_text", "SecondPayload_text"} <= operations
