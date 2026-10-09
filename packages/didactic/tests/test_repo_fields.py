"""Field-addressable schemas and field blame for ``Repository.add(Model)``."""

import json
from typing import TYPE_CHECKING, Annotated, Literal, cast

import panproto
import pytest
from annotated_types import Ge

import didactic.api as dx
from didactic.vcs._repo import protocol_from_model, schema_from_model

if TYPE_CHECKING:
    from pathlib import Path

    from didactic.types._typing import Opaque


class RefTarget(dx.Model):
    id: str = dx.field(nominal=True)


class EmbeddedValue(dx.Model):
    label: str


class Event(dx.TaggedUnion, discriminator="kind"):
    pass


class Created(Event):
    kind: Literal["created"]
    value: int


class FieldKinds(dx.Model):
    scalar: int
    linked: dx.Ref[RefTarget]
    embedded: dx.Embed[EmbeddedValue]
    event: Event


class StoredRecord(dx.Model):
    id: str = dx.field(nominal=True)
    count: int


class AliasedRecord(dx.Model):
    identifier: str = dx.field(alias="record_id", nominal=True)
    count: int


class MetadataRecord(dx.Model):
    count: Annotated[int, Ge(0)] = dx.field(
        default=0,
        usage_mode="materialised",
    )


def _named_model(
    name: str,
    annotations: dict[str, type],
    fields: dict[str, dx.Field] | None = None,
) -> type[dx.Model]:
    """Build a Model whose display name can be shared across revisions."""
    namespace: dict[str, Opaque] = {"__annotations__": annotations}
    namespace.update(fields or {})
    return type(name, (dx.Model,), namespace)


def _committed_schema(path: Path, model: type[dx.Model]) -> panproto.Schema:
    """Commit ``model`` through didactic and read its stored schema."""
    repo = dx.Repository.init(path)
    repo.add(model)
    commit_id = repo.commit("model", author="Audit <audit@example.com>")
    return panproto.Repository.open(str(path)).schema_at(commit_id)


def _constraint_map(schema: panproto.Schema, vertex_id: str) -> dict[str, str]:
    """Index a field vertex's constraints by their declared sort."""
    return {
        constraint.sort: constraint.value
        for constraint in schema.constraints_for(vertex_id)
    }


def test_same_named_models_with_different_fields_commit_different_schemas(
    tmp_path: Path,
) -> None:
    old = _named_model("RunSpec", {"point_id": str, "seed": int})
    new = _named_model("RunSpec", {"run_id": str, "seed": int})

    old_schema = _committed_schema(tmp_path / "old", old)
    new_schema = _committed_schema(tmp_path / "new", new)

    assert old_schema.to_json() != new_schema.to_json()
    assert old_schema.has_vertex("RunSpec.point_id")
    assert not old_schema.has_vertex("RunSpec.run_id")
    assert new_schema.has_vertex("RunSpec.run_id")
    assert not new_schema.has_vertex("RunSpec.point_id")


def test_same_named_models_with_a_changed_field_type_have_distinct_schemas(
    tmp_path: Path,
) -> None:
    old = _named_model("Measurement", {"value": int})
    new = _named_model("Measurement", {"value": str})

    old_schema = _committed_schema(tmp_path / "old-type", old)
    new_schema = _committed_schema(tmp_path / "new-type", new)

    assert old_schema.to_json() != new_schema.to_json()
    assert _constraint_map(old_schema, "Measurement.value")["didactic:sort"] == "Int"
    assert _constraint_map(new_schema, "Measurement.value")["didactic:sort"] == "String"


def test_every_field_kind_has_a_deterministic_addressable_vertex() -> None:
    schema = schema_from_model(FieldKinds)
    edges = {edge.name: edge for edge in schema.outgoing_edges("FieldKinds")}

    assert set(edges) == {"scalar", "linked", "embedded", "event"}
    expected_roles = {
        "scalar": "scalar",
        "linked": "ref",
        "embedded": "embed",
        "event": "sum",
    }
    for field_name, role in expected_roles.items():
        vertex_id = f"FieldKinds.{field_name}"
        vertex = schema.vertex(vertex_id)
        assert vertex is not None
        assert vertex.kind == "field"
        assert edges[field_name].src == "FieldKinds"
        assert edges[field_name].tgt == vertex_id
        constraints = _constraint_map(schema, vertex_id)
        assert (
            constraints["didactic:sort"] == FieldKinds.__field_specs__[field_name].sort
        )
        assert constraints["didactic:kind"] == role
        assert constraints["didactic:required"] == "true"
        assert constraints["didactic:usage-mode"] == "readwrite"


def test_field_vertex_ids_and_schema_serialization_are_deterministic() -> None:
    first = schema_from_model(FieldKinds)
    second = schema_from_model(FieldKinds)

    assert first.to_json() == second.to_json()
    assert {vertex.id for vertex in first.vertices} == {
        "FieldKinds",
        "FieldKinds.scalar",
        "FieldKinds.linked",
        "FieldKinds.embedded",
        "FieldKinds.event",
    }


def test_nominal_and_structural_field_identity_are_preserved() -> None:
    nominal_model = _named_model(
        "IdentityRecord",
        {"identifier": str, "label": str},
        {"identifier": dx.field(nominal=True)},
    )
    structural_model = _named_model(
        "IdentityRecord",
        {"identifier": str, "label": str},
    )

    nominal_schema = schema_from_model(nominal_model)
    structural_schema = schema_from_model(structural_model)
    raw_nominal = nominal_schema.to_dict()["nominal"]
    raw_structural = structural_schema.to_dict()["nominal"]

    assert isinstance(raw_nominal, dict)
    assert isinstance(raw_structural, dict)
    nominal = cast("dict[str, bool]", raw_nominal)
    structural = cast("dict[str, bool]", raw_structural)
    assert nominal == {
        "IdentityRecord.identifier": True,
        "IdentityRecord.label": False,
    }
    assert structural == {
        "IdentityRecord.identifier": False,
        "IdentityRecord.label": False,
    }
    assert nominal_schema.to_json() != structural_schema.to_json()


def test_field_schema_validates_against_its_model_protocol() -> None:
    schema = schema_from_model(FieldKinds)
    assert schema.validate(protocol_from_model(FieldKinds)) == []


def test_field_constraints_preserve_requiredness_usage_mode_and_axioms() -> None:
    schema = schema_from_model(MetadataRecord)
    constraints = _constraint_map(schema, "MetadataRecord.count")

    assert constraints["didactic:required"] == "false"
    assert constraints["didactic:usage-mode"] == "materialised"
    assert constraints["didactic:axiom"]


def test_every_declared_field_is_blameable(tmp_path: Path) -> None:
    repo = dx.Repository.init(tmp_path / "repo")
    repo.add(FieldKinds)
    commit_id = repo.commit("initial model", author="Audit <audit@example.com>")

    for field_name in FieldKinds.__field_specs__:
        blame = repo.blame_field("HEAD", FieldKinds, field_name)
        assert isinstance(blame, dx.Blame)
        assert blame.commit_id == commit_id
        assert blame.author == "Audit <audit@example.com>"
        assert blame.message == "initial model"


def test_blame_field_rejects_an_undeclared_field(tmp_path: Path) -> None:
    repo = dx.Repository.init(tmp_path / "repo")
    repo.add(FieldKinds)
    repo.commit("initial model", author="Audit <audit@example.com>")

    with pytest.raises(KeyError, match="has no field 'missing'"):
        repo.blame_field("HEAD", FieldKinds, "missing")


def test_blame_distinguishes_existing_and_new_fields(tmp_path: Path) -> None:
    old = _named_model("AuditRecord", {"id": str})
    new = _named_model("AuditRecord", {"id": str, "label": str})
    repo = dx.Repository.init(tmp_path / "repo")
    repo.add(old)
    first = repo.commit("initial model", author="First <first@example.com>")
    repo.add(new)
    second = repo.commit("add label", author="Second <second@example.com>")

    assert repo.blame_field("HEAD", new, "id").commit_id == first
    assert repo.blame_field("HEAD", new, "label").commit_id == second


def test_blame_follows_a_field_rename_through_the_committed_migration(
    tmp_path: Path,
) -> None:
    old = _named_model(
        "RunSpec",
        {"point_id": str, "seed": int},
        {"point_id": dx.field(nominal=True)},
    )
    new = _named_model(
        "RunSpec",
        {"run_id": str, "seed": int},
        {"run_id": dx.field(nominal=True)},
    )
    repo = dx.Repository.init(tmp_path / "repo")
    repo.add(old)
    first = repo.commit("initial model", author="First <first@example.com>")
    repo.add(new)
    repo.commit("rename point id", author="Second <second@example.com>")

    blame = repo.blame_field("HEAD", new, "run_id")
    assert blame.commit_id == first
    assert blame.message == "initial model"


def test_serialized_alias_rename_retains_field_identity(tmp_path: Path) -> None:
    old = _named_model(
        "AliasedRecord",
        {"identifier": str},
        {"identifier": dx.field(alias="point_id", nominal=True)},
    )
    new = _named_model(
        "AliasedRecord",
        {"identifier": str},
        {"identifier": dx.field(alias="run_id", nominal=True)},
    )
    repo = dx.Repository.init(tmp_path / "repo")
    repo.add(old)
    first = repo.commit("initial alias", author="First <first@example.com>")
    repo.add(new)
    second = repo.commit(
        "rename serialized field", author="Second <second@example.com>"
    )

    assert repo.blame_field("HEAD", new, "identifier").commit_id == first
    schema = panproto.Repository.open(str(tmp_path / "repo")).schema_at(second)
    (edge,) = schema.outgoing_edges("AliasedRecord")
    assert edge.name == "run_id"


def test_field_vertex_codec_round_trip_covers_every_field_role() -> None:
    value = FieldKinds(
        scalar=7,
        linked="target-1",
        embedded=EmbeddedValue(label="inside"),
        event=Created(kind="created", value=11),
    )

    dx.codegen.io.check_round_trip("avro", value)


def test_field_vertex_codec_round_trip_uses_serialized_aliases() -> None:
    value = AliasedRecord.model_validate({"identifier": "rec-1", "count": 3})

    assert json.loads(value.model_dump_json(by_alias=True)) == {
        "record_id": "rec-1",
        "count": 3,
    }
    dx.codegen.io.check_round_trip("avro", value)


def test_model_data_stages_replays_and_validates_with_field_vertices(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    repo = dx.Repository.init(repo_path)
    repo.add(StoredRecord)
    data_path = tmp_path / "records.json"
    records = [{"id": "a", "count": 1}, {"id": "b", "count": 2}]
    data_path.write_text(json.dumps(records))
    repo.add_data(data_path, key="records")
    commit_id = repo.commit("schema and data", author="Audit <audit@example.com>")

    inner = panproto.Repository.open(str(repo_path))
    stored_schema = inner.schema_at(commit_id)
    assert stored_schema.validate(protocol_from_model(StoredRecord)) == []
    decoded = inner.decoded_data_at(commit_id)
    assert decoded == [
        {
            "schema_id": decoded[0]["schema_id"],
            "records": records,
            "record_count": 2,
            "key": "records",
        }
    ]
