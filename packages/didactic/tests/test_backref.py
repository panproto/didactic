"""Tests for ``dx.resolve_backrefs`` and ``dx.ModelPool``."""

from __future__ import annotations

import pytest

import didactic.api as dx


# -- model definitions reused across the tests -------------------------


class Author(dx.Model):
    id: str
    name: str


class Book(dx.Model):
    id: str
    title: str
    author: dx.Ref[Author]


# -- direct resolver --------------------------------------------------


def test_resolve_backrefs_filters_by_id() -> None:
    ada = Author(id="a1", name="Ada Lovelace")
    grace = Author(id="a2", name="Grace Hopper")
    books = [
        Book(id="b1", title="Notes on the Engine", author="a1"),
        Book(id="b2", title="A History of Computing", author="a2"),
        Book(id="b3", title="More Notes", author="a1"),
    ]

    refs_to_ada = dx.resolve_backrefs(ada, books, via="author")
    assert [b.id for b in refs_to_ada] == ["b1", "b3"]

    refs_to_grace = dx.resolve_backrefs(grace, books, via="author")
    assert [b.id for b in refs_to_grace] == ["b2"]


def test_resolve_backrefs_returns_empty_when_no_match() -> None:
    nobody = Author(id="x", name="No One")
    books = [Book(id="b1", title="A Book", author="a1")]
    assert dx.resolve_backrefs(nobody, books, via="author") == []


def test_resolve_backrefs_accepts_iterators() -> None:
    """The ``candidates`` arg is consumed once; an iterator works too."""
    ada = Author(id="a1", name="Ada")
    books = iter([Book(id="b1", title="A", author="a1")])
    refs = dx.resolve_backrefs(ada, books, via="author")
    assert len(refs) == 1


def test_resolve_backrefs_alternate_key() -> None:
    """The ``key`` argument lets us match on a non-default field."""

    class Tag(dx.Model):
        slug: str
        label: str

    class Post(dx.Model):
        id: str
        tag_slug: str

    music = Tag(slug="music", label="Music")
    posts = [
        Post(id="p1", tag_slug="music"),
        Post(id="p2", tag_slug="news"),
    ]
    refs = dx.resolve_backrefs(music, posts, via="tag_slug", key="slug")
    assert [p.id for p in refs] == ["p1"]


# -- ModelPool --------------------------------------------------------


def test_pool_starts_empty() -> None:
    pool = dx.ModelPool()
    assert len(pool) == 0


def test_pool_groups_by_concrete_class() -> None:
    pool = dx.ModelPool()
    pool.add(Author(id="a1", name="Ada"))
    pool.add(Book(id="b1", title="t", author="a1"))
    pool.add(Book(id="b2", title="t", author="a1"))

    assert len(pool) == 3
    assert len(pool.all_of(Author)) == 1
    assert len(pool.all_of(Book)) == 2


def test_pool_initial_instances_constructor() -> None:
    pool = dx.ModelPool(
        [
            Author(id="a1", name="Ada"),
            Book(id="b1", title="t", author="a1"),
        ]
    )
    assert len(pool.all_of(Author)) == 1
    assert len(pool.all_of(Book)) == 1


def test_pool_add_returns_instance_for_chaining() -> None:
    pool = dx.ModelPool()
    ada = pool.add(Author(id="a1", name="Ada"))
    assert isinstance(ada, Author)
    assert ada.id == "a1"


def test_pool_backrefs_finds_references() -> None:
    pool = dx.ModelPool()
    ada = pool.add(Author(id="a1", name="Ada"))
    pool.add(Book(id="b1", title="A", author="a1"))
    pool.add(Book(id="b2", title="B", author="a2"))
    pool.add(Book(id="b3", title="C", author="a1"))

    refs = pool.backrefs(ada, Book, via="author")
    assert [b.id for b in refs] == ["b1", "b3"]


def test_pool_backrefs_empty_when_class_not_registered() -> None:
    pool = dx.ModelPool()
    ada = Author(id="a1", name="Ada")
    # no Books registered
    assert pool.backrefs(ada, Book, via="author") == []


def test_pool_repr_summarises_counts() -> None:
    pool = dx.ModelPool()
    pool.add(Author(id="a1", name="Ada"))
    pool.add(Book(id="b1", title="t", author="a1"))
    assert "Author=1" in repr(pool)
    assert "Book=1" in repr(pool)


def test_pool_repr_when_empty() -> None:
    pool = dx.ModelPool()
    assert repr(pool) == "ModelPool()"


# -- error paths ------------------------------------------------------


def test_resolve_backrefs_raises_on_missing_via_field() -> None:
    ada = Author(id="a1", name="Ada")
    # candidate has no ``not_a_real_field`` attribute
    with pytest.raises(AttributeError):
        dx.resolve_backrefs(ada, [ada], via="not_a_real_field")
