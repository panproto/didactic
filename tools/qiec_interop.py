"""Run the Didactic/Panproto/QIEC prerequisite contract fixtures.

This is an executable cross-repository probe, not a QIEC implementation.
Quivers owns the QIEC records and checker. Didactic sequences checking and
lowering, while Panproto carries the resulting versioned wire document as a
JSON-Schema instance.

Run from the Didactic checkout::

    uv run python tools/qiec_interop.py
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

import panproto

from didactic.extensions import LoweringRoute, lower_checked

if TYPE_CHECKING:
    from didactic.types._typing import Opaque

QVR_SOURCE_VERSION = "qvr-source/v0.19"
QIEC_ABI = "qiec-core/v1alpha1"
QIEC_WIRE_FORMAT = "qiec-json/v1"
QIEC_SCHEMA_ID = "https://quivers.dev/schemas/qiec-json/v1"
QIEC_PREVIOUS_SCHEMA_ID = "https://quivers.dev/schemas/qiec-json/v0"


@dataclass(frozen=True, slots=True)
class _QiecSource:
    families: tuple[Opaque, ...] = ()
    constructors: tuple[Opaque, ...] = ()
    effects: tuple[Opaque, ...] = ()
    handlers: tuple[Opaque, ...] = ()
    computation: Opaque | None = None
    expected: Opaque | None = None
    extras: tuple[Opaque, ...] = ()


@dataclass(frozen=True, slots=True)
class _CheckedQiecSource:
    source: _QiecSource
    inferred: Opaque


class _QiecLowerer:
    route = LoweringRoute(QVR_SOURCE_VERSION, QIEC_ABI)

    def __init__(self, qiec: ModuleType) -> None:
        self._qiec = qiec

    def check(self, source: _QiecSource, /) -> _CheckedQiecSource:
        qiec = self._qiec
        registry = qiec.KernelRegistry()
        for family in source.families:
            registry.register_family(family)
        for constructor in source.constructors:
            registry.register_constructor(constructor)
        for effect in source.effects:
            registry.register_effect(effect)
        for handler in source.handlers:
            registry.register_handler(handler)
        if source.computation is None:
            raise TypeError("a QIEC fixture must contain a computation")
        inferred = qiec.infer_computation(source.computation, registry)
        if source.expected is not None and inferred != source.expected:
            raise TypeError(
                f"QIEC type mismatch: expected {source.expected!r}, got {inferred!r}"
            )
        return _CheckedQiecSource(source, inferred)

    def lower(self, checked: _CheckedQiecSource, /) -> tuple[Opaque, ...]:
        source = checked.source
        return (
            *source.families,
            *source.constructors,
            *source.effects,
            *source.handlers,
            source.computation,
            checked.inferred,
            *source.extras,
        )

    def validate(self, target: tuple[Opaque, ...], /) -> None:
        encoded = self._qiec.dumps(target)
        if self._qiec.loads(encoded) != target:
            raise TypeError("QIEC validation round trip changed the lowered graph")


def _load_qiec(quivers_root: Path) -> ModuleType:
    package_root = quivers_root / "src" / "quivers"
    if not (package_root / "qiec" / "__init__.py").is_file():
        raise FileNotFoundError(f"QIEC package not found under {quivers_root}")

    # import the self-contained QIEC package without executing quivers.__init__,
    # which loads unrelated runtime backends that Didactic does not require.
    package = ModuleType("quivers")
    package.__path__ = [str(package_root)]  # type: ignore[attr-defined]
    sys.modules["quivers"] = package
    from quivers import qiec  # noqa: PLC0415

    if qiec.QIEC_ABI != QIEC_ABI or qiec.QIEC_WIRE_FORMAT != QIEC_WIRE_FORMAT:
        raise RuntimeError(
            "fixture supports exactly "
            f"{QIEC_WIRE_FORMAT!r}/{QIEC_ABI!r}, got "
            f"{qiec.QIEC_WIRE_FORMAT!r}/{qiec.QIEC_ABI!r}"
        )
    return qiec


def _vec_fixture(qiec: ModuleType) -> _QiecSource:
    nat = qiec.UserIndexSort("Nat", ("Z", "S"), (0, 1))
    zero = qiec.IndexConstructor("Z", (), nat)
    family_id = qiec.FamilyId.derive("interop", "Vec")
    nil_id = qiec.ConstructorId.derive(family_id, "Nil")
    cons_id = qiec.ConstructorId.derive(family_id, "Cons")
    family = qiec.FamilyDecl(
        family_id,
        "Vec",
        (qiec.TypeBinder("A"),),
        (qiec.IndexBinder("n", nat, refinable=True),),
        (nil_id, cons_id),
    )
    nil = qiec.ConstructorDecl(nil_id, family_id, "Nil", (), (), (zero,))
    predecessor = qiec.IndexVariable("m", nat)
    cons = qiec.ConstructorDecl(
        cons_id,
        family_id,
        "Cons",
        (qiec.IndexBinder("m", nat),),
        (
            qiec.FieldDef("head", qiec.TypeVariable("A")),
            qiec.FieldDef(
                "tail",
                qiec.TypeApplication(
                    family.type_constructor,
                    (qiec.TypeVariable("A"), predecessor),
                ),
            ),
        ),
        (qiec.IndexConstructor("S", (predecessor,), nat),),
    )

    vec_zero = qiec.TypeApplication(family.type_constructor, (qiec.INT, zero))
    successor_zero = qiec.IndexConstructor("S", (zero,), nat)
    vec_one = qiec.TypeApplication(
        family.type_constructor,
        (qiec.INT, successor_zero),
    )
    nil_value = qiec.ConstructorValue(nil_id, (qiec.INT,), (), vec_zero)
    cons_value = qiec.ConstructorValue(
        cons_id,
        (qiec.INT, zero),
        (qiec.LiteralValue(1, qiec.INT), nil_value),
        vec_one,
    )

    branch_scope = qiec.StaticScopeId.derive("interop", "Vec.head", "Cons")
    branch_index = qiec.constructor_skolems(cons, branch_scope)[0]
    head = qiec.Local("head", qiec.INT)
    tail = qiec.Local(
        "tail",
        qiec.TypeApplication(family.type_constructor, (qiec.INT, branch_index)),
    )
    case = qiec.Case(
        cons_value,
        qiec.CaseMotive(
            (qiec.IndexBinder("result_n", nat, refinable=True),),
            qiec.INT,
        ),
        (
            qiec.CaseBranch(
                cons_id,
                (branch_index,),
                (head, tail),
                qiec.Return(qiec.Var(head)),
                branch_scope,
            ),
        ),
    )
    origin = qiec.SourceOrigin(
        "interop.vec",
        ("families", "Vec", "head", "case"),
        "indexed-case",
        QVR_SOURCE_VERSION,
        "interop.qvr",
        8,
        3,
    )
    return _QiecSource(
        families=(family,),
        constructors=(nil, cons),
        computation=case,
        expected=qiec.ComputationType(qiec.EMPTY_ROW, qiec.INT),
        extras=(origin, origin.site_id()),
    )


def _state_fixture(qiec: ModuleType) -> _QiecSource:
    state_id = qiec.EffectId.derive("interop", "State", 1)
    get_id = qiec.OperationId.derive(state_id, "get")
    put_id = qiec.OperationId.derive(state_id, "put")
    get = qiec.OperationDef(
        get_id,
        "get",
        (),
        (),
        qiec.TypeVariable("state"),
    )
    put = qiec.OperationDef(
        put_id,
        "put",
        (),
        (qiec.ArgumentDef("value", qiec.TypeVariable("state")),),
        qiec.UNIT,
    )
    state = qiec.EffectDef(
        qiec.EffectRef(state_id, "State", 1),
        (qiec.TypeBinder("state"),),
        (get, put),
        qiec.InterfaceEvolution.FORWARDING,
    )
    int_state = state.apply((qiec.INT,))
    string_state = state.apply((qiec.STRING,))
    left = qiec.instantiate_effect(
        int_state,
        module="interop.state",
        lexical_path=("body", "left"),
    )
    right = qiec.instantiate_effect(
        int_state,
        module="interop.state",
        lexical_path=("body", "right"),
    )
    tail = qiec.RowVariable(
        "rho",
        qiec.RowVariableId.derive("interop", "state-tail"),
        (left.instance, right.instance),
    )
    open_row = qiec.EffectRow((left, right), tail)
    total_handler = qiec.HandlerDef(
        qiec.HandlerId.derive("interop", "run-state-int"),
        "run-state-int",
        int_state,
        (
            qiec.HandlerClauseDef(get_id, qiec.ResumptionGrade.LINEAR),
            qiec.HandlerClauseDef(put_id, qiec.ResumptionGrade.ZERO),
        ),
        qiec.INT,
        qiec.INT,
        total=True,
    )
    partial_handler = qiec.HandlerDef(
        qiec.HandlerId.derive("interop", "inspect-state-int"),
        "inspect-state-int",
        int_state,
        (qiec.HandlerClauseDef(get_id, qiec.ResumptionGrade.AFFINE),),
        qiec.INT,
        qiec.INT,
        total=False,
    )
    forwarding_handler = qiec.HandlerDef(
        qiec.HandlerId.derive("interop", "forward-state-int"),
        "forward-state-int",
        int_state,
        (qiec.HandlerClauseDef(get_id, qiec.ResumptionGrade.UNRESTRICTED),),
        qiec.INT,
        qiec.INT,
        total=False,
        forwards_unknown=True,
    )
    origin = qiec.SiteProvenance(
        qiec.SourceOrigin(
            "interop.state",
            ("body", "left", "get"),
            "State.get",
            QVR_SOURCE_VERSION,
            "interop.qvr",
            19,
            7,
        )
    )
    request = qiec.EffectRequest(
        left.instance,
        int_state,
        get_id,
        (),
        (),
        qiec.INT,
        origin,
    )
    computation = qiec.Handle(
        left.instance,
        total_handler.id,
        qiec.Perform(request),
    )
    return _QiecSource(
        effects=(state,),
        handlers=(total_handler, partial_handler, forwarding_handler),
        computation=computation,
        expected=qiec.ComputationType(qiec.EMPTY_ROW, qiec.INT),
        extras=(int_state, string_state, left, right, open_row, request),
    )


def _escaping_fixture(qiec: ModuleType) -> _QiecSource:
    family_id = qiec.FamilyId.derive("interop", "EscapingPack")
    constructor_id = qiec.ConstructorId.derive(family_id, "Pack")
    family = qiec.FamilyDecl(
        family_id,
        "EscapingPack",
        (),
        (),
        (constructor_id,),
    )
    constructor = qiec.ConstructorDecl(
        constructor_id,
        family_id,
        "Pack",
        (qiec.TypeBinder("packed"),),
        (qiec.FieldDef("value", qiec.TypeVariable("packed")),),
        (),
    )
    packed_type = qiec.TypeApplication(family.type_constructor)
    scrutinee = qiec.ConstructorValue(
        constructor_id,
        (qiec.STRING,),
        (qiec.LiteralValue("hidden", qiec.STRING),),
        packed_type,
    )
    scope = qiec.StaticScopeId.derive("interop", "escaping-pack")
    skolem = qiec.constructor_skolems(constructor, scope)[0]
    field = qiec.Local("hidden", skolem)
    computation = qiec.Case(
        scrutinee,
        qiec.CaseMotive((), skolem),
        (
            qiec.CaseBranch(
                constructor_id,
                (skolem,),
                (field,),
                qiec.Return(qiec.Var(field)),
                scope,
            ),
        ),
    )
    return _QiecSource(
        families=(family,),
        constructors=(constructor,),
        computation=computation,
    )


def _carrier_schema(*, previous: bool = False) -> tuple[panproto.Schema, str]:
    schema_id = QIEC_PREVIOUS_SCHEMA_ID if previous else QIEC_SCHEMA_ID
    abi_field = "core" if previous else "abi"
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "type": "object",
        "required": ["$schema", abi_field, "root"],
        "additionalProperties": False,
        "properties": {
            "$schema": {"const": QIEC_WIRE_FORMAT},
            abi_field: {"const": QIEC_ABI},
            "root": {},
        },
    }
    return panproto.parse_schema_document("json_schema", document), schema_id


def _panproto_round_trip(qiec: ModuleType, graph: tuple[Opaque, ...]) -> Opaque:
    schema, root = _carrier_schema()
    encoded = qiec.dumps(graph)
    instance = panproto.Instance.from_json(schema, root, encoded)
    if instance.validate():
        raise TypeError(f"Panproto rejected the QIEC carrier: {instance.validate()!r}")
    emitted = instance.to_json()
    restored = qiec.loads(emitted)
    if restored != graph:
        raise TypeError("Panproto changed the QIEC graph")
    if qiec.dumps(restored) != encoded:
        raise TypeError(
            "the canonical QIEC bytes changed after the Panproto round trip"
        )
    return restored


def _migration_fixture(qiec: ModuleType, graph: tuple[Opaque, ...]) -> Opaque:
    current = json.loads(qiec.dumps(graph))
    previous = {
        "$schema": current["$schema"],
        "core": current["abi"],
        "root": current["root"],
    }
    source_schema, source_root = _carrier_schema(previous=True)
    source = panproto.Instance.from_json(
        source_schema,
        source_root,
        json.dumps(previous, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
    )
    migration = panproto.ProtolensChain.from_dsl_json(
        json.dumps(
            {
                "id": "qiec-json-carrier-v0-to-v1",
                "source": "qiec-json-carrier/v0",
                "target": "qiec-json-carrier/v1",
                "steps": [{"rename_field": {"old": "core", "new": "abi"}}],
            }
        ),
        source_root,
    )
    lens = migration.instantiate(
        source_schema,
        panproto.get_builtin_protocol("json-schema"),
    )
    migrated, _complement = lens.get(source)
    errors = migrated.validate()
    if errors:
        raise TypeError(f"Panproto carrier migration is invalid: {errors!r}")
    restored = qiec.loads(migrated.to_json())
    if restored != graph:
        raise TypeError("the explicit carrier migration changed the QIEC graph")
    return restored


def _unknown_node_fails_closed(qiec: ModuleType) -> bool:
    schema, root = _carrier_schema()
    malformed = {
        "$schema": QIEC_WIRE_FORMAT,
        "abi": QIEC_ABI,
        "root": {"$type": "terms.FutureNode", "fields": []},
    }
    carried = panproto.Instance.from_json(
        schema,
        root,
        json.dumps(malformed, separators=(",", ":"), sort_keys=True),
    )
    try:
        qiec.loads(carried.to_json())
    except qiec.SerializationError:
        return True
    return False


def _escaping_skolem_fails_closed(qiec: ModuleType, lowerer: _QiecLowerer) -> bool:
    try:
        lower_checked(
            _escaping_fixture(qiec),
            lowerer,
            source_version=QVR_SOURCE_VERSION,
            target_version=QIEC_ABI,
        )
    except qiec.KernelError:
        return True
    return False


def _default_quivers_root() -> Path:
    return Path(__file__).resolve().parents[3] / "quivers"


def main() -> None:
    """Run both fixtures and print their verified contract properties."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--quivers-root",
        type=Path,
        default=_default_quivers_root(),
    )
    args = parser.parse_args()
    qiec = _load_qiec(args.quivers_root.resolve())
    lowerer = _QiecLowerer(qiec)

    vec = lower_checked(
        _vec_fixture(qiec),
        lowerer,
        source_version=QVR_SOURCE_VERSION,
        target_version=QIEC_ABI,
    )
    state = lower_checked(
        _state_fixture(qiec),
        lowerer,
        source_version=QVR_SOURCE_VERSION,
        target_version=QIEC_ABI,
    )
    _panproto_round_trip(qiec, vec)
    _panproto_round_trip(qiec, state)
    _migration_fixture(qiec, vec)

    state_source = _state_fixture(qiec)
    int_state = state_source.extras[0]
    string_state = state_source.extras[1]
    left = state_source.extras[2]
    right = state_source.extras[3]
    open_row = state_source.extras[4]
    result = {
        "panproto": panproto.__version__,
        "route": f"{QVR_SOURCE_VERSION} -> {QIEC_ABI}",
        "wire": QIEC_WIRE_FORMAT,
        "vec": {
            "single_cons_branch_is_total_for_vec_s_n": True,
            "panproto_round_trip": True,
        },
        "state": {
            "applied_effect": str(state_source.effects[0].apply((qiec.INT,)).id),
            "applied_effect_arguments_distinct": int_state != string_state,
            "lexical_instances_distinct": left.instance != right.instance,
            "open_row_preserved": open_row.tail is not None,
            "handler_modes": [
                "total",
                "partial",
                "forwarding",
            ],
            "resumption_grades": [
                clause.grade.value
                for handler in state_source.handlers
                for clause in handler.clauses
            ],
            "panproto_round_trip": True,
        },
        "migration": "qiec-json-carrier/v0 -> qiec-json-carrier/v1",
        "fail_closed": {
            "unknown_node": _unknown_node_fails_closed(qiec),
            "escaping_skolem": _escaping_skolem_fails_closed(qiec, lowerer),
        },
    }
    if not all(result["fail_closed"].values()):
        raise RuntimeError("a fail-closed fixture was unexpectedly accepted")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
