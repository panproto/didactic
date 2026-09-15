"""Declaring generalized algebraic theories from keyword telescopes."""

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
    dx.Operation,
]:
    lang = dx.GADT("ExprLanguage")
    Ty = lang.sort("Ty", closed=True)
    El = lang.family("El", t=Ty)
    Expr = lang.family("Expr", t=Ty, closed=True)
    int_code = lang.constructor("int_code", returns=Ty)
    bool_code = lang.constructor("bool_code", returns=Ty)
    int_value = lang.operation("int_value", returns=El[int_code()])
    bool_value = lang.operation("bool_value", returns=El[bool_code()])
    IntLit = lang.constructor("IntLit", value=El[int_code()], returns=Expr[int_code()])
    lang.constructor("BoolLit", value=El[bool_code()], returns=Expr[bool_code()])
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
    return (
        lang,
        Ty,
        El,
        Expr,
        int_code,
        bool_code,
        int_value,
        bool_value,
        IntLit,
        evaluate,
    )


def test_dependent_motive_compiles_and_is_preserved() -> None:
    lang, _, El, _, int_code, _, _, _, _, evaluate = _expr_language()
    compiled = lang.compile()
    assert compiled.eq_count == 1
    assert evaluate.motive == dx.Motive(El[dx.Var("t")])
    assert evaluate.motive is not None
    assert evaluate.motive.at(t=int_code()) == El[int_code()]


def test_user_defined_eliminator_reduces_symbolically() -> None:
    lang, _, _, _, int_code, _, int_value, _, IntLit, evaluate = _expr_language()
    term = evaluate(int_code(), IntLit(int_value()))
    assert lang.normalize(term) == int_value()


def test_dependent_motive_rejects_wrong_branch_result() -> None:
    lang, _, El, Expr, int_code, bool_code, int_value, _, _, _ = _expr_language()
    # A fresh invalid declaration: compiled declarations are sealed.
    broken = dx.GADT("BrokenExpr")
    BrokenTy = broken.sort("BrokenTy", closed=True)
    BrokenEl = broken.family("BrokenEl", t=BrokenTy)
    BrokenExprFamily = broken.family("BrokenExprFamily", t=BrokenTy, closed=True)
    broken_int = broken.constructor("broken_int", returns=BrokenTy)
    broken_bool = broken.constructor("broken_bool", returns=BrokenTy)
    make_integer = broken.operation("make_integer", returns=BrokenEl[broken_int()])
    broken.constructor(
        "BrokenIntLit",
        value=BrokenEl[broken_int()],
        returns=BrokenExprFamily[broken_int()],
    )
    broken.constructor(
        "BrokenBoolLit",
        value=BrokenEl[broken_bool()],
        returns=BrokenExprFamily[broken_bool()],
    )
    broken.eliminator(
        "broken_evaluate",
        t=BrokenTy,
        expression=lambda t: BrokenExprFamily[t],
        returns=lambda t: BrokenEl[t],
        body=lambda t, expression: dx.match(
            expression,
            BrokenIntLit=lambda value: value,
            BrokenBoolLit=lambda value: make_integer(),
        ),
    )
    with pytest.raises(panproto.GatError, match="BrokenBoolLit"):
        broken.compile()

    # Keep references live so strict type checking confirms the original
    # declaration objects have the promised public types.
    assert El[int_code()] != El[bool_code()]
    assert Expr[int_code()].name == "Expr"
    assert int_value.owner is lang


def test_index_refines_exhaustive_case_coverage() -> None:
    lang = dx.GADT("VectorLanguage")
    Nat = lang.sort("Nat", closed=True)
    Value = lang.sort("Value")
    Vec = lang.family("Vec", length=Nat, closed=True)
    zero = lang.constructor("zero", returns=Nat)
    succ = lang.constructor("succ", n=Nat, returns=Nat)
    nil = lang.constructor("nil", returns=Vec[zero()])
    cons = lang.constructor(
        "cons", n=Nat, head=Value, tail=lambda n: Vec[n], returns=lambda n: Vec[succ(n)]
    )
    fallback = lang.operation("fallback", returns=Value)
    head = lang.eliminator(
        "head",
        n=Nat,
        vector=lambda n: Vec[succ(n)],
        returns=Value,
        body=lambda n, vector: dx.match(vector, cons=lambda m, value, tail: value),
    )
    panproto.typecheck_theory(lang.compile())
    assert lang.normalize(head(zero(), cons(zero(), fallback(), nil()))) == fallback()
    tail_case = dx.match(
        cons(zero(), fallback(), nil()),
        cons=lambda m, value, tail: tail,
    )
    assert lang.infer_sort(tail_case) == Vec[zero()]


def test_unreachable_constructor_branch_is_rejected() -> None:
    lang = dx.GADT("UnreachableVector")
    UNat = lang.sort("UNat", closed=True)
    UElement = lang.sort("UElement")
    UVec = lang.family("UVec", length=UNat, closed=True)
    uzero = lang.constructor("uzero", returns=UNat)
    usucc = lang.constructor("usucc", n=UNat, returns=UNat)
    lang.constructor("unil", returns=UVec[uzero()])
    lang.constructor(
        "ucons",
        n=UNat,
        value=UElement,
        tail=lambda n: UVec[n],
        returns=lambda n: UVec[usucc(n)],
    )
    ufallback = lang.operation("ufallback", returns=UElement)
    lang.eliminator(
        "uhead",
        n=UNat,
        vector=lambda n: UVec[usucc(n)],
        returns=UElement,
        body=lambda n, vector: dx.match(
            vector,
            unil=ufallback,
            ucons=lambda m, value, tail: value,
        ),
    )
    with pytest.raises(panproto.GatError, match="unreachable"):
        lang.compile()


def test_branch_local_constructor_index_cannot_escape() -> None:
    lang = dx.GADT("ExistentialPackage")
    PackageCode = lang.sort("PackageCode", closed=True)
    PackageElement = lang.family("PackageElement", code=PackageCode)
    Package = lang.sort("Package", closed=True)
    package_integer = lang.constructor("package_integer", returns=PackageCode)
    lang.constructor("package_boolean", returns=PackageCode)
    lang.constructor(
        "pack",
        code=PackageCode,
        value=lambda code: PackageElement[code],
        returns=Package,
    )
    escape_body = dx.match(dx.Var("package"), pack=lambda hidden, value: value)
    with pytest.raises(dx.GADTDeclarationError, match="branch-local.*escape"):
        lang.infer_sort(escape_body, context={"package": Package()})

    lang.eliminator(
        "escape_package",
        package=Package,
        returns=PackageElement[package_integer()],
        body=lambda package: dx.match(package, pack=lambda hidden, value: value),
    )
    with pytest.raises(panproto.GatError):
        lang.compile()


def test_user_defined_equality_evidence_supports_transport() -> None:
    lang = dx.GADT("EqualityTransport")
    EqualityCode = lang.sort("EqualityCode")
    EqualityElement = lang.family("EqualityElement", code=EqualityCode)
    Equality = lang.family(
        "Equality", left=EqualityCode, right=EqualityCode, closed=True
    )
    refl = lang.constructor(
        "refl", code=EqualityCode, returns=lambda code: Equality[code, code]
    )
    transport = lang.eliminator(
        "transport",
        left=EqualityCode,
        right=EqualityCode,
        proof=lambda left, right: Equality[left, right],
        value=lambda left: EqualityElement[left],
        returns=lambda right: EqualityElement[right],
        body=lambda left, right, proof, value: dx.match(proof, refl=lambda same: value),
    )
    equality_integer = lang.operation("equality_integer", returns=EqualityCode)
    equality_value = lang.operation(
        "equality_value", returns=EqualityElement[equality_integer()]
    )

    term = transport(
        equality_integer(),
        equality_integer(),
        refl(equality_integer()),
        equality_value(),
    )
    assert lang.infer_sort(term) == EqualityElement[equality_integer()]
    assert lang.normalize(term) == equality_value()
    panproto.typecheck_theory(lang.compile())


def test_arbitrary_multi_index_family() -> None:
    lang = dx.GADT("MatrixLanguage")
    MatrixNat = lang.sort("MatrixNat")
    Matrix = lang.family("Matrix", rows=MatrixNat, columns=MatrixNat)
    rows = lang.operation("rows", returns=MatrixNat)
    columns = lang.operation("columns", returns=MatrixNat)
    make_matrix = lang.operation("make_matrix", returns=Matrix[rows(), columns()])
    assert lang.infer_sort(make_matrix()) == Matrix[rows(), columns()]
    panproto.typecheck_theory(lang.compile())


def test_family_parameters_form_a_dependent_heterogeneous_telescope() -> None:
    lang = dx.GADT("DependentTelescope")
    TelescopeContext = lang.sort("TelescopeContext")
    TelescopeType = lang.family("TelescopeType", context=TelescopeContext)
    TelescopeTerm = lang.family(
        "TelescopeTerm",
        context=TelescopeContext,
        type=lambda context: TelescopeType[context],
        closed=True,
    )
    empty_context = lang.operation("empty_context", returns=TelescopeContext)
    unit_type = lang.operation(
        "unit_type",
        context=TelescopeContext,
        returns=lambda context: TelescopeType[context],
    )
    unit_term = lang.constructor(
        "unit_term",
        context=TelescopeContext,
        returns=lambda context: TelescopeTerm[context, unit_type(context)],
    )

    value = unit_term(empty_context())
    assert (
        lang.infer_sort(value)
        == TelescopeTerm[empty_context(), unit_type(empty_context())]
    )
    panproto.typecheck_theory(lang.compile())


def test_implicit_index_is_inferred_from_explicit_argument() -> None:
    lang = dx.GADT("ImplicitVector")
    INat = lang.sort("INat", closed=True)
    IElement = lang.sort("IElement")
    IVec = lang.family("IVec", length=INat, closed=True)
    izero = lang.constructor("izero", returns=INat)
    isucc = lang.constructor("isucc", n=INat, returns=INat)
    inil = lang.constructor("inil", returns=IVec[izero()])
    ifirst = lang.operation("ifirst", returns=IElement)
    icons = lang.constructor(
        "icons",
        n=dx.Implicit(INat),
        value=IElement,
        tail=lambda n: IVec[n],
        returns=lambda n: IVec[isucc(n)],
    )
    term = icons(ifirst(), inil())
    assert lang.infer_sort(term) == IVec[isucc(izero())]
    panproto.typecheck_theory(lang.compile())


def test_eliminator_equation_infers_implicit_index() -> None:
    lang = dx.GADT("ImplicitEliminator")
    IENat = lang.sort("IENat", closed=True)
    IEElement = lang.sort("IEElement")
    IEVec = lang.family("IEVec", length=IENat, closed=True)
    iezero = lang.constructor("iezero", returns=IENat)
    iesucc = lang.constructor("iesucc", n=IENat, returns=IENat)
    ienil = lang.constructor("ienil", returns=IEVec[iezero()])
    iefirst = lang.operation("iefirst", returns=IEElement)
    iecons = lang.constructor(
        "iecons",
        n=dx.Implicit(IENat),
        value=IEElement,
        tail=lambda n: IEVec[n],
        returns=lambda n: IEVec[iesucc(n)],
    )
    iehead = lang.eliminator(
        "iehead",
        n=dx.Implicit(IENat),
        vector=lambda n: IEVec[iesucc(n)],
        returns=IEElement,
        body=lambda n, vector: dx.match(vector, iecons=lambda m, value, tail: value),
    )

    term = iehead(iecons(iefirst(), ienil()))
    assert lang.infer_sort(term) == IEElement()
    assert lang.normalize(term) == iefirst()
    panproto.typecheck_theory(lang.compile())


def test_compile_seals_the_language() -> None:
    lang = dx.GADT("Sealed")
    SealedSort = lang.sort("SealedSort")
    lang.operation("sealed_value", returns=SealedSort)
    assert lang.compile() is lang.compile()
    with pytest.raises(dx.GADTDeclarationError, match="sealed"):
        lang.sort("TooLate")


def test_non_constructor_cannot_target_closed_family() -> None:
    lang = dx.GADT("Closure")
    ClosedFamily = lang.sort("ClosedFamily", closed=True)
    with pytest.raises(dx.GADTDeclarationError, match="non-constructor"):
        lang.operation("illegal", returns=ClosedFamily)


def test_eliminator_without_a_body_is_declared_only() -> None:
    lang = dx.GADT("DeclaredOnly")
    Code = lang.sort("Code", closed=True)
    Carrier = lang.family("Carrier", c=Code)
    Tree = lang.family("Tree", c=Code, closed=True)
    before = lang.definition_count
    fold = lang.eliminator(
        "fold", c=Code, tree=lambda c: Tree[c], returns=lambda c: Carrier[c]
    )
    assert fold.role == "eliminator"
    assert fold.motive == dx.Motive(Carrier[dx.Var("c")])
    assert lang.definition_count == before


def test_define_checks_the_body_binds_every_input_in_order() -> None:
    lang = dx.GADT("Drift")
    Code = lang.sort("Code", closed=True)
    Out = lang.sort("Out")
    Tree = lang.family("Tree", c=Code, closed=True)
    out = lang.operation("out", returns=Out)
    fold = lang.eliminator("fold", c=Code, tree=lambda c: Tree[c], returns=Out)
    with pytest.raises(
        dx.GADTDeclarationError, match=r"\['tree'\] must be the inputs in order"
    ):
        fold.define(lambda tree: out())


def test_match_rejects_a_constructor_the_scrutinee_cannot_have() -> None:
    lang = dx.GADT("Misspelt")
    Code = lang.sort("Code", closed=True)
    Size = lang.sort("Size")
    Node = lang.family("Node", c=Code, closed=True)
    leaf_code = lang.constructor("leaf_code", returns=Code)
    lang.constructor("Leaf", returns=Node[leaf_code()])
    one = lang.operation("one", returns=Size)
    with pytest.raises(
        dx.GADTDeclarationError, match="'Leav' is not a constructor.*Leaf"
    ):
        lang.eliminator(
            "size",
            c=Code,
            node=lambda c: Node[c],
            returns=Size,
            body=lambda c, node: dx.match(node, Leav=one),
        )


def test_match_checks_binder_count_against_the_constructor() -> None:
    lang = dx.GADT("Arity")
    Code = lang.sort("Code", closed=True)
    Out = lang.sort("Out")
    Pair = lang.family("Pair", c=Code, closed=True)
    one = lang.constructor("one", returns=Code)
    lang.constructor("Both", left=Code, right=Code, returns=Pair[one()])
    out = lang.operation("out", returns=Out)
    with pytest.raises(
        dx.GADTDeclarationError, match="binds 1 name but the constructor has 2"
    ):
        lang.eliminator(
            "first",
            c=Code,
            pair=lambda c: Pair[c],
            returns=Out,
            body=lambda c, pair: dx.match(pair, Both=lambda left: out()),
        )


def test_dependence_on_a_name_that_is_not_an_earlier_input_is_rejected() -> None:
    lang = dx.GADT("Scope")
    Code = lang.sort("Code")
    Box = lang.family("Box", c=Code)
    with pytest.raises(
        dx.GADTDeclarationError, match="depends on 'cdoe'.*earlier inputs are c"
    ):
        lang.operation("unwrap", c=Code, box=lambda cdoe: Box[cdoe], returns=Code)


def test_indexed_family_must_be_applied_to_be_a_sort() -> None:
    lang = dx.GADT("Bare")
    Code = lang.sort("Code")
    Box = lang.family("Box", c=Code)
    with pytest.raises(
        dx.GADTDeclarationError, match=r"takes 1 index; write Box\[\.\.\.\]"
    ):
        lang.operation("unwrap", b=Box, returns=Code)


def test_term_spec_round_trip_covers_every_term_form() -> None:
    term = dx.Let(
        "x",
        dx.App("zero", ()),
        dx.Case(
            dx.Var("subject"),
            (
                dx.Branch(
                    "succ",
                    ("predecessor",),
                    dx.App("pair", (dx.Var("x"), dx.hole("remaining"))),
                ),
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
    let_term = dx.Let(
        "y", dx.App("zero", ()), dx.App("pair", (dx.Var("x"), dx.Var("y")))
    )
    substituted_let = let_term.substitute({"x": dx.Var("y")})
    assert isinstance(substituted_let, dx.Let)
    assert substituted_let.name != "y"
    assert substituted_let.free_vars() == frozenset(("y",))

    case_term = dx.match(
        dx.Var("subject"), some=lambda y: dx.App("pair", (dx.Var("x"), y))
    )
    substituted_case = case_term.substitute({"x": dx.Var("y")})
    assert isinstance(substituted_case, dx.Case)
    assert substituted_case.branches[0].binders != ("y",)
    assert "y" in substituted_case.free_vars()


def test_let_binds_the_lambda_parameter_name() -> None:
    _, _, _, _, _, _, int_value, _, IntLit, _ = _expr_language()
    term = dx.let(int_value(), lambda x: IntLit(x))  # noqa: PLW0108 - the lambda form is the subject
    assert isinstance(term, dx.Let)
    assert term.name == "x"
    assert term.body == IntLit(dx.Var("x"))


def test_an_operation_may_stand_for_a_body_that_only_applies_it() -> None:
    _, _, _, _, _, _, int_value, _, IntLit, _ = _expr_language()
    # A unary operation as a let body binds its own input name.
    spelled_out = dx.let(int_value(), lambda value: IntLit(value))  # noqa: PLW0108
    assert dx.let(int_value(), IntLit) == spelled_out
    # A nullary operation as a branch body binds nothing.
    branch = dx.match(dx.Var("v"), unit=int_value)
    assert branch.branches[0].binders == ()
    assert branch.branches[0].body == int_value()


@given(st.text(min_size=1).filter(str.isidentifier))
def test_variable_spec_round_trip_property(name: str) -> None:
    """Every valid generated identifier survives canonical term transport."""
    if not name.isascii():
        return
    variable = dx.Var(name)
    assert dx.term_from_spec(variable.to_spec()) == variable


def test_normalization_fuel_stops_nonterminating_rewrite() -> None:
    lang = dx.GADT("Looping")
    LoopSort = lang.sort("LoopSort")
    loop_value = lang.operation("loop_value", returns=LoopSort)
    loop = lang.operation("loop", value=LoopSort, returns=LoopSort)
    loop_var = dx.Var("value")
    lang.rewrite("loop_forever", loop(loop_var), loop(loop_var))
    with pytest.raises(dx.GADTReductionError, match="exceeded 3 steps"):
        lang.normalize(loop(loop_value()), max_steps=3)


def _indexed_box_language(name: str, *, shifted: bool) -> dx.GADT:
    lang = dx.GADT(name)
    MorphismNat = lang.sort("MorphismNat", closed=True)
    MorphismBox = lang.family("MorphismBox", n=MorphismNat, closed=True)
    morphism_zero = lang.constructor("morphism_zero", returns=MorphismNat)
    morphism_succ = lang.constructor(
        "morphism_succ", n=MorphismNat, returns=MorphismNat
    )
    index = morphism_succ(morphism_zero()) if shifted else morphism_zero()
    lang.constructor("morphism_box", returns=MorphismBox[index])
    return lang


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
    lang = dx.GADT(name)
    ColimitNat = lang.sort("ColimitNat", closed=True)
    colimit_zero = lang.constructor("colimit_zero", returns=ColimitNat)
    colimit_succ = lang.constructor("colimit_succ", n=ColimitNat, returns=ColimitNat)
    return lang, ColimitNat, colimit_zero, colimit_succ


def test_colimit_preserves_independent_indexed_families() -> None:
    shared, _, _, _ = _natural_numbers("ColimitShared")
    left, ColimitNat, colimit_zero, colimit_succ = _natural_numbers("ColimitLeft")
    ColimitVec = left.family("ColimitVec", n=ColimitNat, closed=True)
    left.constructor("colimit_nil", returns=ColimitVec[colimit_zero()])
    left.constructor(
        "colimit_cons",
        n=ColimitNat,
        tail=lambda n: ColimitVec[n],
        returns=lambda n: ColimitVec[colimit_succ(n)],
    )

    right, RightNat, _, _ = _natural_numbers("ColimitRight")
    ColimitBox = right.family("ColimitBox", n=RightNat, closed=True)
    right.constructor("colimit_box", n=RightNat, returns=lambda n: ColimitBox[n])

    combined = panproto.colimit_theories(
        left.compile(), right.compile(), shared.compile()
    )
    panproto.typecheck_theory(combined)
    sort_items = cast("list[JsonObject]", combined.to_dict()["sorts"])
    sorts = {cast("str", item["name"]): item for item in sort_items}
    assert sorts["ColimitVec"]["params"] == [{"name": "n", "sort": "ColimitNat"}]
    assert sorts["ColimitBox"]["params"] == [{"name": "n", "sort": "ColimitNat"}]
