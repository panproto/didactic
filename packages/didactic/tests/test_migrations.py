"""Tests for register_migration / migrate."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import didactic.api as dx
from didactic.migrations._migrations import clear_registry, lookup_migration

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from didactic.types._typing import JsonValue


@pytest.fixture(autouse=True)
def isolated_registry() -> Iterator[None]:
    """Each test starts with an empty migration registry."""
    clear_registry()
    yield


# -- a representative versioned pair ----------------------------------


class UserV1(dx.Model):
    id: str
    name: str


class UserV2(dx.Model):
    id: str
    given_name: str
    family_name: str = ""


class V1ToV2(dx.Iso[UserV1, UserV2]):
    """Reversible migration: split ``name`` into given/family parts."""

    def forward(self, u: UserV1) -> UserV2:
        first, _, last = u.name.partition(" ")
        return UserV2(id=u.id, given_name=first, family_name=last)

    def backward(self, u: UserV2) -> UserV1:
        return UserV1(id=u.id, name=f"{u.given_name} {u.family_name}".rstrip())


# -- registration ------------------------------------------------------


def test_register_migration_succeeds() -> None:
    dx.register_migration(UserV1, UserV2, V1ToV2())


def test_register_migration_rejects_duplicates() -> None:
    dx.register_migration(UserV1, UserV2, V1ToV2())
    with pytest.raises(TypeError, match="already registered"):
        dx.register_migration(UserV1, UserV2, V1ToV2())


# -- migrate -----------------------------------------------------------


def test_migrate_instance() -> None:
    dx.register_migration(UserV1, UserV2, V1ToV2())
    v1 = UserV1(id="u1", name="Ada Lovelace")
    v2 = dx.migrate(v1, target=UserV2)
    assert isinstance(v2, UserV2)
    assert v2.given_name == "Ada"
    assert v2.family_name == "Lovelace"


def test_migrate_dict_payload() -> None:
    dx.register_migration(UserV1, UserV2, V1ToV2())
    payload: dict[str, JsonValue] = {"id": "u1", "name": "Ada Lovelace"}
    v2 = dx.migrate(payload, source=UserV1, target=UserV2)
    assert isinstance(v2, UserV2)
    assert v2.given_name == "Ada"


def test_migrate_dict_requires_source() -> None:
    dx.register_migration(UserV1, UserV2, V1ToV2())
    with pytest.raises(TypeError, match="`source=` is required"):
        dx.migrate({"id": "u1", "name": "Ada"}, target=UserV2)


def test_migrate_no_path() -> None:
    class Unrelated(dx.Model):
        x: str

    with pytest.raises(LookupError, match="no migration path"):
        dx.migrate(UserV1(id="u1", name="Ada"), target=Unrelated)


def test_migrate_target_equals_source_is_noop() -> None:
    v1 = UserV1(id="u1", name="Ada")
    out = dx.migrate(v1, target=UserV1)
    assert out is v1


# -- chain through multiple registered hops ----------------------------


class UserV3(dx.Model):
    id: str
    given_name: str
    family_name: str = ""
    display_name: str = ""


class V2ToV3(dx.Iso[UserV2, UserV3]):
    def forward(self, u: UserV2) -> UserV3:
        return UserV3(
            id=u.id,
            given_name=u.given_name,
            family_name=u.family_name,
            display_name=f"{u.given_name} {u.family_name}".rstrip(),
        )

    def backward(self, u: UserV3) -> UserV2:
        return UserV2(id=u.id, given_name=u.given_name, family_name=u.family_name)


def test_migrate_chain_through_two_hops() -> None:
    dx.register_migration(UserV1, UserV2, V1ToV2())
    dx.register_migration(UserV2, UserV3, V2ToV3())

    v1 = UserV1(id="u1", name="Ada Lovelace")
    v3 = dx.migrate(v1, target=UserV3)
    assert isinstance(v3, UserV3)
    assert v3.display_name == "Ada Lovelace"


# -- structural equivalence -------------------------------------------


def test_migrate_uses_structural_fingerprint() -> None:
    """A registered migration is found via a structurally-identical class.

    The fingerprint normalises the model's display name, so registering
    ``UserV1 -> UserV2`` and looking up under a different but
    structurally-identical pair finds the same lens.
    """
    dx.register_migration(UserV1, UserV2, V1ToV2())

    # define a structurally-identical pair under fresh class names
    class PersonV1(dx.Model):
        id: str
        name: str

    class PersonV2(dx.Model):
        id: str
        given_name: str
        family_name: str = ""

    p = PersonV1(id="u1", name="Ada Lovelace")
    out = dx.migrate(p, target=PersonV2)

    # the registered lens constructs UserV2 instances, not PersonV2
    # instances; the structural-equivalence guarantee is that the lens
    # is found, not that it returns the looked-up class
    assert isinstance(out, UserV2)
    assert out.given_name == "Ada"
    assert out.family_name == "Lovelace"


def test_lookup_migration_finds_structurally_identical_pair() -> None:
    dx.register_migration(UserV1, UserV2, V1ToV2())

    class PersonV1(dx.Model):
        id: str
        name: str

    class PersonV2(dx.Model):
        id: str
        given_name: str
        family_name: str = ""

    assert lookup_migration(PersonV1, PersonV2) is not None


# -- persistence -------------------------------------------------------


def test_save_and_load_registry_round_trip(tmp_path: Path) -> None:
    """save_registry writes JSON; load_registry confirms in-memory entries."""
    dx.register_migration(UserV1, UserV2, V1ToV2())
    path = tmp_path / "registry.json"
    dx.save_registry(path)

    confirmed = dx.load_registry(path)
    assert confirmed == 1


def test_load_registry_reports_missing_entries(tmp_path: Path) -> None:
    """An entry on disk that has no in-memory match shows up as a gap."""
    dx.register_migration(UserV1, UserV2, V1ToV2())
    path = tmp_path / "registry.json"
    dx.save_registry(path)

    # wipe the in-memory registry; loading the disk file should report 0
    # confirmed entries (the disk record exists, but no live lens matches it)
    from didactic.migrations._migrations import clear_registry as _clear

    _clear()
    assert dx.load_registry(path) == 0


def test_load_registry_rejects_bad_format(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"unrelated": []}')
    with pytest.raises(ValueError, match="not a didactic migration registry"):
        dx.load_registry(path)


def test_save_registry_writes_human_readable_json(tmp_path: Path) -> None:
    dx.register_migration(UserV1, UserV2, V1ToV2())
    path = tmp_path / "registry.json"
    dx.save_registry(path)

    import json

    payload = json.loads(path.read_text())
    assert "entries" in payload
    assert len(payload["entries"]) == 1
    entry = payload["entries"][0]
    assert "source_fp" in entry
    assert "target_fp" in entry
    assert "source_spec" in entry
    assert "target_spec" in entry
    assert entry["lens_qualname"].endswith("V1ToV2")
