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


def _build_minimal_schema() -> panproto.Schema:
    """Construct a minimal panproto schema for staging tests.

    A schema with no vertices is rejected by the validator, so we add
    a single ``string`` vertex to satisfy the protocol's edge rules.
    """
    proto = panproto.get_builtin_protocol("openapi")
    builder = proto.schema()
    builder.vertex("ping", "string")
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


def test_add_accepts_model_class(fresh_repo_path: Path) -> None:
    """``Repository.add`` accepts a Model class and stages its synthesised schema."""

    class StagedModel(dx.Model):
        id: str

    repo = dx.Repository.init(fresh_repo_path)
    repo.add(StagedModel)
    assert repo.has_staged() is True
    cid = repo.commit("model", author="Test <test@example.com>")
    assert repo.head() == cid
