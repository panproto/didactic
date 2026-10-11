"""Tests for the didactic Repository wrapper.

The wrapper delegates to ``panproto._native.Repository``; these tests
exercise the surface didactic exposes (constructors, introspection
accessors, and the ``add``/``commit`` round trip).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import panproto

import didactic.api as dx


@pytest.fixture()
def fresh_repo_path(tmp_path: Path) -> Path:
    """Return a directory path that does not yet contain a repository."""
    return tmp_path / "repo"


# -- construction ------------------------------------------------------


def test_init_creates_repository(fresh_repo_path: Path) -> None:
    repo = dx.Repository.init(fresh_repo_path)
    assert isinstance(repo, dx.Repository)
    assert Path(repo.working_dir) == fresh_repo_path


def test_init_accepts_pathlike(fresh_repo_path: Path) -> None:
    """``init`` accepts both ``str`` and ``PathLike`` arguments."""
    repo = dx.Repository.init(str(fresh_repo_path))
    assert isinstance(repo, dx.Repository)


def test_open_finds_existing_repo(fresh_repo_path: Path) -> None:
    dx.Repository.init(fresh_repo_path)
    repo = dx.Repository.open(fresh_repo_path)
    assert isinstance(repo, dx.Repository)
    assert Path(repo.working_dir) == fresh_repo_path


def test_open_missing_path_raises(tmp_path: Path) -> None:
    with pytest.raises(panproto.VcsError):
        dx.Repository.open(tmp_path / "does-not-exist")


def test_repr_includes_working_dir(fresh_repo_path: Path) -> None:
    repo = dx.Repository.init(fresh_repo_path)
    assert "Repository(at=" in repr(repo)
    assert str(fresh_repo_path) in repr(repo)


# -- introspection on a fresh repo ------------------------------------


def test_fresh_repo_has_no_head(fresh_repo_path: Path) -> None:
    repo = dx.Repository.init(fresh_repo_path)
    assert repo.head() is None


def test_fresh_repo_head_state_is_main_ref(fresh_repo_path: Path) -> None:
    repo = dx.Repository.init(fresh_repo_path)
    assert "refs/heads/main" in repo.head_state()


def test_fresh_repo_has_nothing_staged(fresh_repo_path: Path) -> None:
    repo = dx.Repository.init(fresh_repo_path)
    assert repo.has_staged() is False


def test_fresh_repo_has_no_branches_or_tags(fresh_repo_path: Path) -> None:
    """A freshly initialised repo has no concrete branches or tags yet.

    The ``main`` branch only materialises after the first commit; until
    then the head points at an unborn ref.
    """
    repo = dx.Repository.init(fresh_repo_path)
    assert repo.list_branches() == []
    assert repo.list_tags() == []


# -- staging and committing -------------------------------------------


def _build_minimal_schema(vertex: str = "ping") -> panproto.Schema:
    """Construct a minimal panproto schema for staging tests.

    A schema with no vertices is rejected by the validator, so we add
    a single ``string`` vertex to satisfy the protocol's edge rules.
    Passing a distinct ``vertex`` name yields a schema that differs from
    the default, which a second commit needs to avoid panproto's
    ``"no changes detected"`` rejection.
    """
    proto = panproto.get_builtin_protocol("openapi")
    builder = proto.schema()
    builder.vertex(vertex, "string")
    return builder.build()


def test_add_then_commit_advances_head(fresh_repo_path: Path) -> None:
    repo = dx.Repository.init(fresh_repo_path)
    schema = _build_minimal_schema()
    repo.add(schema)
    assert repo.has_staged() is True

    commit_id = repo.commit("initial", author="Test <test@example.com>")
    assert isinstance(commit_id, str)
    assert repo.head() == commit_id
    assert repo.has_staged() is False


def test_log_lists_committed_changes(fresh_repo_path: Path) -> None:
    repo = dx.Repository.init(fresh_repo_path)
    repo.add(_build_minimal_schema())
    repo.commit("first", author="Test <test@example.com>")

    log = repo.log()
    assert len(log) == 1


def test_resolve_ref_finds_committed_id(fresh_repo_path: Path) -> None:
    repo = dx.Repository.init(fresh_repo_path)
    repo.add(_build_minimal_schema())
    cid = repo.commit("first", author="Test <test@example.com>")
    assert repo.resolve_ref("main") == cid


def test_branch_creation_and_checkout(fresh_repo_path: Path) -> None:
    repo = dx.Repository.init(fresh_repo_path)
    repo.add(_build_minimal_schema())
    cid = repo.commit("first", author="Test <test@example.com>")

    repo.create_branch("feature", cid)
    branch_names = {name for name, _ in repo.list_branches()}
    assert "feature" in branch_names

    repo.checkout_branch("feature")
    assert repo.resolve_ref("HEAD") == cid


# -- tags -------------------------------------------------------------


def _committed_repo(path: Path) -> tuple[dx.Repository, str]:
    """Initialise a repo with a single commit; return it and the commit id."""
    repo = dx.Repository.init(path)
    repo.add(_build_minimal_schema())
    cid = repo.commit("first", author="Test <test@example.com>")
    return repo, cid


def test_create_tag_lists_the_tag(fresh_repo_path: Path) -> None:
    repo, cid = _committed_repo(fresh_repo_path)

    repo.create_tag("v1", cid)
    tag_names = {name for name, _ in repo.list_tags()}
    assert "v1" in tag_names
    assert repo.resolve_ref("v1") == cid


def test_create_tag_duplicate_raises(fresh_repo_path: Path) -> None:
    repo, cid = _committed_repo(fresh_repo_path)
    repo.create_tag("v1", cid)

    with pytest.raises(panproto.VcsError):
        repo.create_tag("v1", cid)


def test_create_tag_force_overwrites(fresh_repo_path: Path) -> None:
    """``force=True`` replaces an existing tag instead of raising."""
    repo, cid = _committed_repo(fresh_repo_path)
    repo.create_tag("v1", cid)

    repo.add(_build_minimal_schema("pong"))
    second = repo.commit("second", author="Test <test@example.com>")

    repo.create_tag("v1", second, force=True)
    assert repo.resolve_ref("v1") == second


def test_create_annotated_tag_round_trips(fresh_repo_path: Path) -> None:
    """An annotated tag records its tagger and message.

    The wrapper does not expose reading annotated-tag objects, so the
    round trip is checked through a separately opened panproto handle:
    this confirms the wrapper forwards ``tagger`` and ``message`` in
    panproto's expected order rather than transposed.
    """
    repo, cid = _committed_repo(fresh_repo_path)

    tag_id = repo.create_annotated_tag(
        "v1",
        cid,
        message="release one",
        tagger="Tagger <tag@example.com>",
    )

    tags = dict(repo.list_tags())
    # the tag ref resolves to the returned annotated-tag object, not the commit
    assert tags["v1"] == tag_id
    assert tag_id != cid

    inner = panproto.Repository.open(str(fresh_repo_path))
    annotated = inner.read_annotated_tag(tag_id)
    assert annotated["target"] == cid
    assert annotated["message"] == "release one"
    assert annotated["tagger"] == "Tagger <tag@example.com>"


def test_delete_tag_removes_it(fresh_repo_path: Path) -> None:
    repo, cid = _committed_repo(fresh_repo_path)
    repo.create_tag("v1", cid)

    repo.delete_tag("v1")
    assert repo.list_tags() == []


def test_delete_missing_tag_raises(fresh_repo_path: Path) -> None:
    repo, _ = _committed_repo(fresh_repo_path)

    with pytest.raises(panproto.VcsError):
        repo.delete_tag("nope")


# -- committed data ---------------------------------------------------


_RECORDS = b'[{"id": "a"}, {"id": "b"}]'


def _commit_schema_and_data(path: Path, records: bytes) -> str:
    """Commit a schema plus a staged data file through the public surface."""
    repo = dx.Repository.init(path)
    repo.add(_build_minimal_schema())
    data_file = path / "records.json"
    data_file.write_bytes(records)
    repo.add_data(data_file)
    return repo.commit("schema+data", author="Test <test@example.com>")


def test_data_at_returns_committed_dataset(fresh_repo_path: Path) -> None:
    cid = _commit_schema_and_data(fresh_repo_path, _RECORDS)

    repo = dx.Repository.open(fresh_repo_path)
    datasets = repo.data_at("HEAD")
    assert len(datasets) == 1
    (dataset,) = datasets
    assert isinstance(dataset, dx.CommittedDataset)
    assert dataset.data
    assert dataset.data != _RECORDS
    assert dataset.record_count == 2
    assert dataset.schema_id  # a non-empty object id

    # the same revision is readable by commit id and by branch name
    assert repo.data_at(cid) == datasets
    assert repo.data_at("main") == datasets


def test_decoded_data_at_returns_public_dataset_and_keeps_raw_data(
    fresh_repo_path: Path,
) -> None:
    """Decoded traversal is public while the canonical bytes remain available."""

    class CurrentRecord(dx.Model):
        id: str

    cid = _commit_schema_and_data(fresh_repo_path, _RECORDS)
    repo = dx.Repository.open(fresh_repo_path)

    (raw,) = repo.data_at(cid)
    (decoded,) = repo.decoded_data_at(cid)

    assert isinstance(raw, dx.CommittedDataset)
    assert isinstance(raw.data, bytes)
    assert isinstance(decoded, dx.DecodedCommittedDataset)
    assert decoded.schema_id == raw.schema_id
    assert decoded.record_count == raw.record_count == 2
    assert decoded.key == raw.key
    assert decoded.records == [{"id": "a"}, {"id": "b"}]
    validated: list[CurrentRecord] = []
    for record in decoded.records:
        assert isinstance(record, dict)
        validated.append(CurrentRecord.model_validate(record))
    assert [record.id for record in validated] == ["a", "b"]


def test_decoded_data_at_preserves_mixed_schemas_values_and_order(
    fresh_repo_path: Path,
) -> None:
    """One commit may decode datasets bound to distinct persisted schemas."""
    repo = dx.Repository.init(fresh_repo_path)

    repo.add(_build_minimal_schema("configuration"))
    initial_config = fresh_repo_path / "initial-config.json"
    initial_config.write_text('[{"id": "config-1"}]')
    repo.add_data(initial_config, key="configuration")
    first = repo.commit("configuration", author="Test <test@example.com>")
    config_schema_id = repo.data_at(first)[0].schema_id

    repo.add(_build_minimal_schema("record"))
    initial_record = fresh_repo_path / "initial-record.json"
    initial_record.write_text('[{"id": "record-1"}]')
    repo.add_data(initial_record, key="record")
    repo.commit("record", author="Test <test@example.com>")

    # The first dataset explicitly reuses an older schema. The second uses the
    # schema staged for this commit, without changing HEAD during staging.
    repo.add(_build_minimal_schema("event"))
    configuration_records = [
        {
            "name": "alpha",
            "enabled": True,
            "missing": None,
            "retries": 3,
            "ratio": 1.25,
            "nested": {"labels": ["one", "two"], "empty": []},
        },
        {"name": "omega", "enabled": False, "retries": -1, "ratio": 0.0},
    ]
    event_records = [{"event": "start"}, {"event": "finish"}]
    next_config = fresh_repo_path / "next-config.json"
    next_config.write_text(json.dumps(configuration_records))
    next_event = fresh_repo_path / "next-event.json"
    next_event.write_text(json.dumps(event_records))

    head_before = repo.head()
    repo.add_data(
        next_config,
        key="configuration",
        schema_id=config_schema_id,
    )
    repo.add_data(next_event, key="event")
    assert repo.head() == head_before

    mixed = repo.commit("configuration+event", author="Test <test@example.com>")
    decoded = repo.decoded_data_at(mixed)
    raw = repo.data_at(mixed)

    assert [dataset.key for dataset in decoded] == ["configuration", "event"]
    assert [dataset.records for dataset in decoded] == [
        configuration_records,
        event_records,
    ]
    assert [dataset.record_count for dataset in decoded] == [2, 2]
    assert [dataset.schema_id for dataset in decoded] == [
        config_schema_id,
        raw[1].schema_id,
    ]
    assert decoded[0].schema_id != decoded[1].schema_id


def test_decoded_data_at_accepts_history_refs_without_mutating_state(
    fresh_repo_path: Path,
) -> None:
    """History reads accept every ref form and leave repository state alone."""
    cid = _commit_schema_and_data(fresh_repo_path, _RECORDS)
    repo = dx.Repository.open(fresh_repo_path)
    repo.create_tag("snapshot", cid)
    repo.create_branch("history", cid)

    # Keep an unrelated schema staged while traversing history. Each lookup
    # must leave both HEAD and the index untouched.
    repo.add(_build_minimal_schema("pending"))
    state_before = (repo.head(), repo.head_state(), repo.has_staged())
    expected = repo.decoded_data_at(cid)

    for ref in ("snapshot", "history", cid, cid[:12]):
        assert repo.decoded_data_at(ref) == expected
        assert (repo.head(), repo.head_state(), repo.has_staged()) == state_before


def test_decoded_data_at_is_empty_without_committed_data(
    fresh_repo_path: Path,
) -> None:
    repo, cid = _committed_repo(fresh_repo_path)
    assert repo.decoded_data_at(cid) == []


def test_decoded_data_at_unknown_ref_raises_typed_error(
    fresh_repo_path: Path,
) -> None:
    repo, _ = _committed_repo(fresh_repo_path)
    with pytest.raises(panproto.VcsError):
        repo.decoded_data_at("not-a-ref")


def test_decoded_data_at_missing_commit_object_raises_typed_error(
    fresh_repo_path: Path,
) -> None:
    cid = _commit_schema_and_data(fresh_repo_path, _RECORDS)
    repo = dx.Repository.open(fresh_repo_path)
    commit_object = fresh_repo_path / ".panproto" / "objects" / cid[:2] / cid[2:]
    commit_object.unlink()

    with pytest.raises(panproto.VcsError):
        repo.decoded_data_at("main")


def test_decoded_data_at_tampered_dataset_raises_typed_error(
    fresh_repo_path: Path,
) -> None:
    """Corrupt canonical data cannot escape as an untyped decoder failure."""
    repo = dx.Repository.init(fresh_repo_path)
    repo.add(_build_minimal_schema())
    objects = fresh_repo_path / ".panproto" / "objects"
    before_data = set(objects.glob("*/*"))

    data_file = fresh_repo_path / "records.json"
    data_file.write_bytes(_RECORDS)
    repo.add_data(data_file, key="records")
    after_data = set(objects.glob("*/*"))
    (dataset_object,) = after_data - before_data
    cid = repo.commit("schema+data", author="Test <test@example.com>")

    stored = dataset_object.read_bytes()
    dataset_object.write_bytes(stored[:-1] + bytes([stored[-1] ^ 0xFF]))

    with pytest.raises(panproto.VcsError):
        repo.decoded_data_at(cid)


def test_add_data_stages_then_round_trips(fresh_repo_path: Path) -> None:
    """``add_data`` stages a file that a commit then exposes via ``data_at``."""
    repo = dx.Repository.init(fresh_repo_path)
    repo.add(_build_minimal_schema())
    data_file = fresh_repo_path / "records.json"
    data_file.write_bytes(_RECORDS)

    repo.add_data(data_file)
    assert repo.has_staged() is True

    repo.commit("schema+data", author="Test <test@example.com>")
    (dataset,) = repo.data_at("HEAD")
    assert dataset.data
    assert dataset.data != _RECORDS
    assert dataset.record_count == 2


def test_add_data_without_schema_context_raises(fresh_repo_path: Path) -> None:
    """Staging data needs a staged schema or a commit to bind to."""
    repo = dx.Repository.init(fresh_repo_path)
    data_file = fresh_repo_path / "records.json"
    data_file.write_bytes(_RECORDS)

    with pytest.raises(panproto.VcsError):
        repo.add_data(data_file)


def test_add_data_records_explicit_key(fresh_repo_path: Path) -> None:
    """A key passed to ``add_data`` is surfaced on the committed dataset."""
    repo = dx.Repository.init(fresh_repo_path)
    repo.add(_build_minimal_schema())
    data_file = fresh_repo_path / "records.json"
    data_file.write_bytes(_RECORDS)
    repo.add_data(data_file, key="at://did:plc:abc/app.bsky.feed.post/1")
    repo.commit("schema+data", author="Test <test@example.com>")

    (dataset,) = repo.data_at("HEAD")
    assert dataset.key == "at://did:plc:abc/app.bsky.feed.post/1"


def test_add_data_key_defaults_to_path(fresh_repo_path: Path) -> None:
    """With no key, the dataset key falls back to the source path."""
    repo = dx.Repository.init(fresh_repo_path)
    repo.add(_build_minimal_schema())
    data_file = fresh_repo_path / "records.json"
    data_file.write_bytes(_RECORDS)
    repo.add_data(data_file)
    repo.commit("schema+data", author="Test <test@example.com>")

    (dataset,) = repo.data_at("HEAD")
    assert dataset.key == str(data_file)


def test_data_only_commit_records_new_data(fresh_repo_path: Path) -> None:
    """A data-only change commits and is readable at the new revision.

    panproto lets a commit carry staged data forward without a schema
    change, so ``has_staged`` and ``commit`` agree on staged data.
    """
    repo = dx.Repository.init(fresh_repo_path)
    repo.add(_build_minimal_schema())
    first_file = fresh_repo_path / "a.json"
    first_file.write_bytes(b'[{"id": "a"}]')
    repo.add_data(first_file, key="rec-a")
    first = repo.commit("schema+data", author="Test <test@example.com>")

    # stage only data, with no schema change
    second_file = fresh_repo_path / "b.json"
    second_file.write_bytes(b'[{"id": "b"}]')
    repo.add_data(second_file, key="rec-b")
    assert repo.has_staged() is True

    second = repo.commit("data only", author="Test <test@example.com>")
    assert second != first

    (dataset,) = repo.data_at(second)
    assert dataset.key == "rec-b"
    assert dataset.data
    assert dataset.data != b'[{"id": "b"}]'


def test_add_data_accepts_persisted_schema_id(fresh_repo_path: Path) -> None:
    """A later dataset can bind to an exact non-HEAD persisted schema."""
    repo = dx.Repository.init(fresh_repo_path)

    repo.add(_build_minimal_schema("configuration"))
    initial_config = fresh_repo_path / "initial-config.json"
    initial_config.write_bytes(b'[{"id": "config-1"}]')
    repo.add_data(initial_config, key="configuration")
    first = repo.commit("configuration", author="Test <test@example.com>")
    config_schema_id = repo.data_at(first)[0].schema_id

    repo.add(_build_minimal_schema("record"))
    initial_record = fresh_repo_path / "initial-record.json"
    initial_record.write_bytes(b'[{"id": "record-1"}]')
    repo.add_data(initial_record, key="record")
    second = repo.commit("record", author="Test <test@example.com>")
    record_schema_id = repo.data_at(second)[0].schema_id

    next_config = fresh_repo_path / "next-config.json"
    next_config.write_bytes(b'[{"id": "config-2"}]')
    next_record = fresh_repo_path / "next-record.json"
    next_record.write_bytes(b'[{"id": "record-2"}]')

    head_before = repo.head()
    repo.add_data(
        next_config,
        key="configuration",
        schema_id=config_schema_id,
    )
    repo.add_data(next_record, key="record")
    assert repo.head() == head_before

    third = repo.commit("configuration+record", author="Test <test@example.com>")
    datasets = {dataset.key: dataset for dataset in repo.data_at(third)}
    assert datasets["configuration"].schema_id == config_schema_id
    assert datasets["record"].schema_id == record_schema_id


def test_add_data_rejects_missing_persisted_schema_id(
    fresh_repo_path: Path,
) -> None:
    """The wrapper preserves panproto's typed error for a missing object."""
    repo = dx.Repository.init(fresh_repo_path)
    data_file = fresh_repo_path / "records.json"
    data_file.write_bytes(_RECORDS)

    with pytest.raises(panproto.VcsError):
        repo.add_data(data_file, schema_id="0" * 64)

    assert repo.has_staged() is False


def test_data_at_is_empty_without_committed_data(fresh_repo_path: Path) -> None:
    """A revision that committed only a schema has no datasets."""
    repo, cid = _committed_repo(fresh_repo_path)
    assert repo.data_at(cid) == []


def test_data_at_unknown_ref_raises(fresh_repo_path: Path) -> None:
    repo, _ = _committed_repo(fresh_repo_path)
    with pytest.raises(panproto.VcsError):
        repo.data_at("nope")


def test_add_accepts_model_class(fresh_repo_path: Path) -> None:
    """``Repository.add`` accepts a Model class and stages its synthesised schema."""

    class StagedModel(dx.Model):
        id: str

    repo = dx.Repository.init(fresh_repo_path)
    repo.add(StagedModel)
    assert repo.has_staged() is True
    cid = repo.commit("model", author="Test <test@example.com>")
    assert repo.head() == cid
