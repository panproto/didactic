"""Define a Model, instantiate, and round-trip through JSON.

Run with:

.. code-block:: bash

    python examples/01_basic_model.py
"""

from __future__ import annotations

import didactic.api as dx


class User(dx.Model):
    """A user record."""

    id: str
    email: str = dx.field(description="primary contact")
    nickname: str = ""


def main() -> None:
    """Build a User, dump to JSON, and re-validate it."""
    u = User(id="u1", email="ada@example.org", nickname="ada")
    print(f"instance: {u}")

    # immutability: this raises an AttributeError-like error
    try:
        u.email = "elsewhere@example.org"  # type: ignore[misc]
    except (AttributeError, TypeError) as exc:
        print(f"as expected, immutable: {exc}")

    payload = u.model_dump_json()
    print(f"json: {payload}")

    back = User.model_validate_json(payload)
    print(f"round trip: {back}")
    assert back == u


if __name__ == "__main__":
    main()
