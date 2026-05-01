"""Register a migration and walk a payload forward.

Demonstrates ``register_migration`` plus ``migrate``.
"""

from __future__ import annotations

import didactic.api as dx


class UserV1(dx.Model):
    """Original user shape: a single name field."""

    id: str
    name: str


class UserV2(dx.Model):
    """New user shape: split name into given/family."""

    id: str
    given_name: str
    family_name: str = ""


class V1ToV2(dx.Iso[UserV1, UserV2]):
    """Reversible migration: split ``name`` on whitespace."""

    def forward(self, u: UserV1) -> UserV2:
        first, _, last = u.name.partition(" ")
        return UserV2(id=u.id, given_name=first, family_name=last)

    def backward(self, u: UserV2) -> UserV1:
        return UserV1(id=u.id, name=f"{u.given_name} {u.family_name}".rstrip())


def main() -> None:
    """Register V1->V2 and migrate a payload."""
    dx.register_migration(UserV1, UserV2, V1ToV2())

    v1 = UserV1(id="u1", name="Ada Lovelace")
    print(f"v1: {v1}")

    v2 = dx.migrate(v1, target=UserV2)
    print(f"v2: {v2}")

    # also works on raw dict payloads
    payload = {"id": "u2", "name": "Grace Hopper"}
    v2b = dx.migrate(payload, source=UserV1, target=UserV2)
    print(f"from dict: {v2b}")


if __name__ == "__main__":
    main()
