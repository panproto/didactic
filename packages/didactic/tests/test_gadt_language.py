"""General GADT declarations, motives, eliminators, and reduction."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import panproto
import pytest
from hypothesis import given
from hypothesis import strategies as st

import didactic.api as dx

if TYPE_CHECKING:
    from didactic.types._typing import JsonObject, JsonValue


def _expr_language() -> tuple[
    dx.GADT,
    dx.Family,
    dx.Family,
    dx.Family,
    dx.Operation,
    dx.Operation,
    dx.Operation,
    dx.Operation,
    dx.Operation,
]:
    theory = dx.GADT("ExprLanguage")
    ty = theory.sort("Ty", closed=True)
    el = theory.family("El", parameters=(dx.param("t", ty()),))
    expr = theory.family("Expr", parameters=(dx.param("t", ty()),), closed=True)
    int_code = theory.constructor("int_code", result=ty())
    bool_code = theory.constructor("bool_code", result=ty())
    int_value = theory.operation("int_value", result=el(int_code()))
    bool_value = theory.operation("bool_value", result=el(bool_code()))
    theory.constructor(
        "IntLit",
        inputs=(dx.param("value", el(int_code())),),
        result=expr(int_code()),
    )
    theory.constructor(
        "BoolLit",
        inputs=(dx.param("value", el(bool_code())),),
        result=expr(bool_code()),
    )
    evaluate = theory.eliminator(
        "evaluate",
        inputs=(
            dx.param("t", ty()),
            dx.param("expression", expr(dx.var("t"))),
        ),
        motive=dx.Motive(el(dx.var("t"))),
    )
    evaluate.define(
        dx.case(
            dx.var("expression"),
            dx.branch("IntLit", "value", body=dx.var("value")),
            dx.branch("BoolLit", "value", body=dx.var("value")),
        )
    )
    return (
        theory,
        ty,
        el,
        expr,
        int_code,
        bool_code,
        int_value,
        bool_value,
        evaluate,
    )


def test_dependent_motive_compiles_and_is_preserved() -> None:
    theory, _, el, _, int_code, _, _, _, evaluate = _expr_language()
    compiled = theory.compile()
    assert compiled.eq_count == 1
    assert evaluate.motive == dx.Motive(el(dx.var("t")))
    assert evaluate.motive is not None
    assert evaluate.motive.at(t=int_code()) == el(int_code())


def test_user_defined_eliminator_reduces_symbolically() -> None:
    theory, _, _, _, int_code, _, int_value, _, evaluate = _expr_language()
    int_lit = next(op for op in theory.operations if op.name == "IntLit")
    term = evaluate(int_code(), int_lit(int_value()))
    assert theory.normalize(term) == int_value()


def test_dependent_motive_rejects_wrong_branch_result() -> None:
    theory, _, el, expr, int_code, bool_code, int_value, _, _ = _expr_language()
    # Replace the valid language with the smallest fresh invalid declaration;
    # compiled declarations are sealed and cannot be mutated.
    broken = dx.GADT("BrokenExpr")
    ty = broken.sort("BrokenTy", closed=True)
    carrier = broken.family("BrokenEl", parameters=(dx.param("t", ty()),))
    terms = broken.family(
        "BrokenExprFamily", parameters=(dx.param("t", ty()),), closed=True
    )
    integer = broken.constructor("broken_int", result=ty())
    boolean = broken.constructor("broken_bool", result=ty())
    make_integer = broken.operation("make_integer", result=carrier(integer()))
    broken.constructor(
        "BrokenIntLit",
        inputs=(dx.param("value", carrier(integer())),),
        result=terms(integer()),
    )
    broken.constructor(
        "BrokenBoolLit",
        inputs=(dx.param("value", carrier(boolean())),),
        result=terms(boolean()),
    )
    evaluate = broken.eliminator(
        "broken_evaluate",
        inputs=(
            dx.param("t", ty()),
            dx.param("expression", terms(dx.var("t"))),
        ),
        motive=carrier(dx.var("t")),
    )
    evaluate.define(
        dx.case(
            dx.var("expression"),
            dx.branch("BrokenIntLit", "value", body=dx.var("value")),
            dx.branch("BrokenBoolLit", "value", body=make_integer()),
        )
    )
    with pytest.raises(panproto.GatError, match="BrokenBoolLit"):
        broken.compile()

    # Keep references live so strict type checking confirms the original
    # declaration objects have the promised public types.
    assert el(int_code()) != el(bool_code())
    assert expr(int_code()).name == "Expr"
    assert int_value.owner is theory


def test_index_refines_exhaustive_case_coverage() -> None:
    theory = dx.GADT("VectorLanguage")
    nat = theory.sort("Nat", closed=True)
    value = theory.sort("Value")
    vector = theory.family("Vec", parameters=(dx.param("length", nat()),), closed=True)
    zero = theory.constructor("zero", result=nat())
    succ = theory.constructor("succ", inputs=(dx.param("n", nat()),), result=nat())
    nil = theory.constructor("nil", result=vector(zero()))
    cons = theory.constructor(
        "cons",
        inputs=(
            dx.param("n", nat()),
            dx.param("head", value()),
            dx.param("tail", vector(dx.var("n"))),
        ),
        result=vector(succ(dx.var("n"))),
    )
    fallback = theory.operation("fallback", result=value())
    head = theory.eliminator(
        "head",
        inputs=(
            dx.param("n", nat()),
            dx.param("vector", vector(succ(dx.var("n")))),
        ),
        motive=value(),
    )
    head.define(
        dx.case(
            dx.var("vector"),
            dx.branch("cons", "m", "value", "tail", body=dx.var("value")),
        )
    )
    panproto.typecheck_theory(theory.compile())
    assert theory.normalize(head(zero(), cons(zero(), fallback(), nil()))) == fallback()
    tail_case = dx.case(
        cons(zero(), fallback(), nil()),
        dx.branch("cons", "m", "value", "tail", body=dx.var("tail")),
    )
    assert theory.infer_sort(tail_case) == vector(zero())


def test_unreachable_constructor_branch_is_rejected() -> None:
    theory = dx.GADT("UnreachableVector")
    nat = theory.sort("UNat", closed=True)
    element = theory.sort("UElement")
    vector = theory.family("UVec", parameters=(dx.param("length", nat()),), closed=True)
    zero = theory.constructor("uzero", result=nat())
    succ = theory.constructor("usucc", inputs=(dx.param("n", nat()),), result=nat())
    theory.constructor("unil", result=vector(zero()))
    theory.constructor(
        "ucons",
        inputs=(
            dx.param("n", nat()),
            dx.param("value", element()),
            dx.param("tail", vector(dx.var("n"))),
        ),
        result=vector(succ(dx.var("n"))),
    )
    fallback = theory.operation("ufallback", result=element())
    head = theory.eliminator(
        "uhead",
        inputs=(
            dx.param("n", nat()),
            dx.param("vector", vector(succ(dx.var("n")))),
        ),
        motive=element(),
    )
    head.define(
        dx.case(
            dx.var("vector"),
            dx.branch("unil", body=fallback()),
            dx.branch("ucons", "m", "value", "tail", body=dx.var("value")),
        )
    )
    with pytest.raises(panproto.GatError, match="unreachable"):
        theory.compile()


def test_branch_local_constructor_index_cannot_escape() -> None:
    theory = dx.GADT("ExistentialPackage")
    code = theory.sort("PackageCode", closed=True)
    element = theory.family("PackageElement", parameters=(dx.param("code", code()),))
    package = theory.sort("Package", closed=True)
    integer = theory.constructor("package_integer", result=code())
    theory.constructor("package_boolean", result=code())
    theory.constructor(
        "pack",
        inputs=(
            dx.param("code", code()),
            dx.param("value", element(dx.var("code"))),
        ),
        result=package(),
    )
    escape_body = dx.case(
        dx.var("package"),
        dx.branch("pack", "hidden", "value", body=dx.var("value")),
    )
    with pytest.raises(dx.GADTDeclarationError, match="branch-local.*escape"):
        theory.infer_sort(escape_body, context={"package": package()})

    escape = theory.eliminator(
        "escape_package",
        inputs=(dx.param("package", package()),),
        motive=element(integer()),
    )
    escape.define(escape_body)
    with pytest.raises(panproto.GatError):
        theory.compile()


def test_user_defined_equality_evidence_supports_transport() -> None:
    theory = dx.GADT("EqualityTransport")
    code = theory.sort("EqualityCode")
    element = theory.family("EqualityElement", parameters=(dx.param("code", code()),))
    equality = theory.family(
        "Equality",
        parameters=(
            dx.param("left", code()),
            dx.param("right", code()),
        ),
        closed=True,
    )
    refl = theory.constructor(
        "refl",
        inputs=(dx.param("code", code()),),
        result=equality(dx.var("code"), dx.var("code")),
    )
    transport = theory.eliminator(
        "transport",
        inputs=(
            dx.param("left", code()),
            dx.param("right", code()),
            dx.param("proof", equality(dx.var("left"), dx.var("right"))),
            dx.param("value", element(dx.var("left"))),
        ),
        motive=element(dx.var("right")),
    )
    transport.define(
        dx.case(
            dx.var("proof"),
            dx.branch("refl", "same", body=dx.var("value")),
        )
    )
    integer = theory.operation("equality_integer", result=code())
    value = theory.operation("equality_value", result=element(integer()))

    term = transport(integer(), integer(), refl(integer()), value())
    assert theory.infer_sort(term) == element(integer())
    assert theory.normalize(term) == value()
    panproto.typecheck_theory(theory.compile())


def test_arbitrary_multi_index_family() -> None:
    theory = dx.GADT("MatrixLanguage")
    nat = theory.sort("MatrixNat")
    matrix = theory.family(
        "Matrix",
        parameters=(dx.param("rows", nat()), dx.param("columns", nat())),
    )
    rows = theory.operation("rows", result=nat())
    columns = theory.operation("columns", result=nat())
    make = theory.operation("make_matrix", result=matrix(rows(), columns()))
    assert theory.infer_sort(make()) == matrix(rows(), columns())
    panproto.typecheck_theory(theory.compile())


def test_family_parameters_form_a_dependent_heterogeneous_telescope() -> None:
    theory = dx.GADT("DependentTelescope")
    context = theory.sort("TelescopeContext")
    ty = theory.family("TelescopeType", parameters=(dx.param("context", context()),))
    term = theory.family(
        "TelescopeTerm",
        parameters=(
            dx.param("context", context()),
            dx.param("type", ty(dx.var("context"))),
        ),
        closed=True,
    )
    empty = theory.operation("empty_context", result=context())
    unit = theory.operation(
        "unit_type",
        inputs=(dx.param("context", context()),),
        result=ty(dx.var("context")),
    )
    inhabit = theory.constructor(
        "unit_term",
        inputs=(dx.param("context", context()),),
        result=term(dx.var("context"), unit(dx.var("context"))),
    )

    value = inhabit(empty())
    assert theory.infer_sort(value) == term(empty(), unit(empty()))
    panproto.typecheck_theory(theory.compile())


def test_implicit_index_is_inferred_from_explicit_argument() -> None:
    theory = dx.GADT("ImplicitVector")
    nat = theory.sort("INat", closed=True)
    element = theory.sort("IElement")
    vector = theory.family("IVec", parameters=(dx.param("length", nat()),), closed=True)
    zero = theory.constructor("izero", result=nat())
    theory.constructor("isucc", inputs=(dx.param("n", nat()),), result=nat())
    nil = theory.constructor("inil", result=vector(zero()))
    first = theory.operation("ifirst", result=element())
    cons = theory.constructor(
        "icons",
        inputs=(
            dx.param("n", nat(), implicit=True),
            dx.param("value", element()),
            dx.param("tail", vector(dx.var("n"))),
        ),
        result=vector(dx.app("isucc", dx.var("n"))),
    )
    term = cons(first(), nil())
    assert theory.infer_sort(term) == vector(dx.app("isucc", zero()))
    panproto.typecheck_theory(theory.compile())


def test_eliminator_equation_infers_implicit_index() -> None:
    theory = dx.GADT("ImplicitEliminator")
    nat = theory.sort("IENat", closed=True)
    element = theory.sort("IEElement")
    vector = theory.family(
        "IEVec", parameters=(dx.param("length", nat()),), closed=True
    )
    zero = theory.constructor("iezero", result=nat())
    succ = theory.constructor("iesucc", inputs=(dx.param("n", nat()),), result=nat())
    nil = theory.constructor("ienil", result=vector(zero()))
    first = theory.operation("iefirst", result=element())
    cons = theory.constructor(
        "iecons",
        inputs=(
            dx.param("n", nat(), implicit=True),
            dx.param("value", element()),
            dx.param("tail", vector(dx.var("n"))),
        ),
        result=vector(succ(dx.var("n"))),
    )
    head = theory.eliminator(
        "iehead",
        inputs=(
            dx.param("n", nat(), implicit=True),
            dx.param("vector", vector(succ(dx.var("n")))),
        ),
        motive=element(),
    )
    head.define(
        dx.case(
            dx.var("vector"),
            dx.branch("iecons", "m", "value", "tail", body=dx.var("value")),
        )
    )

    term = head(cons(first(), nil()))
    assert theory.infer_sort(term) == element()
    assert theory.normalize(term) == first()
    panproto.typecheck_theory(theory.compile())


def test_compile_seals_the_language() -> None:
    theory = dx.GADT("Sealed")
    sort = theory.sort("SealedSort")
    theory.operation("sealed_value", result=sort())
    assert theory.compile() is theory.compile()
    with pytest.raises(dx.GADTDeclarationError, match="sealed"):
        theory.sort("TooLate")


def test_non_constructor_cannot_target_closed_family() -> None:
    theory = dx.GADT("Closure")
    closed = theory.sort("ClosedFamily", closed=True)
    with pytest.raises(dx.GADTDeclarationError, match="non-constructor"):
        theory.operation("illegal", result=closed())


def test_term_spec_round_trip_covers_every_term_form() -> None:
    term = dx.let(
        "x",
        dx.app("zero"),
        dx.case(
            dx.var("subject"),
            dx.branch(
                "succ",
                "predecessor",
                body=dx.app("pair", dx.var("x"), dx.hole("remaining")),
            ),
        ),
    )
    assert dx.term_from_spec(term.to_spec()) == term


@pytest.mark.parametrize(
    ("spec", "error", "message"),
    [
        ({}, TypeError, "one-key object"),
        ({"Unknown": None}, ValueError, "unknown term variant"),
        ({"Var": 1}, TypeError, "Var payload"),
        ({"App": {"op": "zero", "args": "wrong"}}, TypeError, "App requires"),
        ({"Case": {"scrutinee": {"Var": "x"}}}, TypeError, "branches"),
    ],
)
def test_malformed_or_unknown_term_variants_fail_closed(
    spec: JsonValue,
    error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error, match=message):
        dx.term_from_spec(spec)


def test_substitution_avoids_capture_in_let_and_case() -> None:
    let_term = dx.let("y", dx.app("zero"), dx.app("pair", dx.var("x"), dx.var("y")))
    substituted_let = let_term.substitute({"x": dx.var("y")})
    assert isinstance(substituted_let, dx.Let)
    assert substituted_let.name != "y"
    assert substituted_let.free_vars() == frozenset(("y",))

    case_term = dx.case(
        dx.var("subject"),
        dx.branch("some", "y", body=dx.app("pair", dx.var("x"), dx.var("y"))),
    )
    substituted_case = case_term.substitute({"x": dx.var("y")})
    assert isinstance(substituted_case, dx.Case)
    assert substituted_case.branches[0].binders != ("y",)
    assert "y" in substituted_case.free_vars()


@given(st.text(min_size=1).filter(str.isidentifier))
def test_variable_spec_round_trip_property(name: str) -> None:
    """Every valid generated identifier survives canonical term transport."""
    if not name.isascii():
        return
    variable = dx.var(name)
    assert dx.term_from_spec(variable.to_spec()) == variable


def test_normalization_fuel_stops_nonterminating_rewrite() -> None:
    theory = dx.GADT("Looping")
    sort = theory.sort("LoopSort")
    value = theory.operation("loop_value", result=sort())
    loop = theory.operation("loop", inputs=(dx.param("value", sort()),), result=sort())
    loop_var = dx.var("value")
    theory.rewrite("loop_forever", loop(loop_var), loop(loop_var))
    with pytest.raises(dx.GADTReductionError, match="exceeded 3 steps"):
        theory.normalize(loop(value()), max_steps=3)


def _indexed_box_language(name: str, *, shifted: bool) -> dx.GADT:
    theory = dx.GADT(name)
    nat = theory.sort("MorphismNat", closed=True)
    box = theory.family("MorphismBox", parameters=(dx.param("n", nat()),), closed=True)
    zero = theory.constructor("morphism_zero", result=nat())
    succ = theory.constructor(
        "morphism_succ", inputs=(dx.param("n", nat()),), result=nat()
    )
    index = succ(zero()) if shifted else zero()
    theory.constructor("morphism_box", result=box(index))
    return theory


def test_morphism_rejects_constructor_that_changes_its_index() -> None:
    source = _indexed_box_language("MorphismSource", shifted=False)
    target = _indexed_box_language("MorphismTarget", shifted=True)
    morphism = cast(
        "dict[str, JsonValue]",
        {
            "name": "index_shifting",
            "domain": "MorphismSource",
            "codomain": "MorphismTarget",
            "sort_map": {"MorphismNat": "MorphismNat", "MorphismBox": "MorphismBox"},
            "op_map": {
                "morphism_zero": "morphism_zero",
                "morphism_succ": "morphism_succ",
                "morphism_box": "morphism_box",
            },
        },
    )
    with pytest.raises(panproto.GatError, match="operation type mismatch"):
        panproto.check_morphism(morphism, source.compile(), target.compile())


def _natural_numbers(
    name: str,
) -> tuple[dx.GADT, dx.Family, dx.Operation, dx.Operation]:
    theory = dx.GADT(name)
    nat = theory.sort("ColimitNat", closed=True)
    zero = theory.constructor("colimit_zero", result=nat())
    succ = theory.constructor(
        "colimit_succ", inputs=(dx.param("n", nat()),), result=nat()
    )
    return theory, nat, zero, succ


def test_colimit_preserves_independent_indexed_families() -> None:
    shared, _, _, _ = _natural_numbers("ColimitShared")
    left, nat, zero, succ = _natural_numbers("ColimitLeft")
    vector = left.family("ColimitVec", parameters=(dx.param("n", nat()),), closed=True)
    left.constructor("colimit_nil", result=vector(zero()))
    left.constructor(
        "colimit_cons",
        inputs=(
            dx.param("n", nat()),
            dx.param("tail", vector(dx.var("n"))),
        ),
        result=vector(succ(dx.var("n"))),
    )

    right, right_nat, _, _ = _natural_numbers("ColimitRight")
    box = right.family(
        "ColimitBox", parameters=(dx.param("n", right_nat()),), closed=True
    )
    right.constructor(
        "colimit_box",
        inputs=(dx.param("n", right_nat()),),
        result=box(dx.var("n")),
    )

    combined = panproto.colimit_theories(
        left.compile(), right.compile(), shared.compile()
    )
    panproto.typecheck_theory(combined)
    sort_items = cast("list[JsonObject]", combined.to_dict()["sorts"])
    sorts = {cast("str", item["name"]): item for item in sort_items}
    assert sorts["ColimitVec"]["params"] == [{"name": "n", "sort": "ColimitNat"}]
    assert sorts["ColimitBox"]["params"] == [{"name": "n", "sort": "ColimitNat"}]
