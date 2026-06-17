"""Tests for the didactic Repository wrapper.

The wrapper delegates to ``panproto._native.Repository``; these tests
exercise the surface didactic exposes (constructors, introspection
accessors, and the ``add``/``commit`` round trip).
"""

from __future__ import annotations

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
    """Commit a schema plus a staged data file through a panproto handle.

    The wrapper does not expose ``add_data``, so the producing side runs
    on a directly opened panproto handle; the test then reads the result
    back through the public ``data_at``.
    """
    inner = panproto.Repository.init(str(path))
    inner.add(_build_minimal_schema())
    data_file = path / "records.json"
    data_file.write_bytes(records)
    inner.add_data(str(data_file))
    return inner.commit("schema+data", "Test <test@example.com>")


def test_data_at_returns_committed_dataset(fresh_repo_path: Path) -> None:
    cid = _commit_schema_and_data(fresh_repo_path, _RECORDS)

    repo = dx.Repository.open(fresh_repo_path)
    datasets = repo.data_at("HEAD")
    assert len(datasets) == 1
    (dataset,) = datasets
    assert isinstance(dataset, dx.CommittedDataset)
    assert dataset.data == _RECORDS
    assert dataset.record_count == 2
    assert dataset.schema_id  # a non-empty object id

    # the same revision is readable by commit id and by branch name
    assert repo.data_at(cid) == datasets
    assert repo.data_at("main") == datasets


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
