"""Round-trip a model between didactic and Pydantic.

Demonstrates ``didactic.pydantic.from_pydantic`` and ``to_pydantic``.
Run with:

.. code-block:: bash

    python examples/04_pydantic_interop.py
"""

from __future__ import annotations

from pydantic import BaseModel, Field

import didactic.api as dx
from didactic.pydantic import from_pydantic, to_pydantic


# start with a Pydantic model
class PydUser(BaseModel):
    """A Pydantic-shaped user."""

    id: str
    email: str = Field(description="primary contact")


def main() -> None:
    """Convert Pydantic -> didactic -> Pydantic; show field metadata survives."""
    DxUser = from_pydantic(PydUser)
    assert issubclass(DxUser, dx.Model)

    u = DxUser(id="u1", email="ada@example.org")
    print(f"didactic instance: {u}")
    print(f"didactic field metadata: {DxUser.__field_specs__['email'].description!r}")

    PydUserBack = to_pydantic(DxUser)
    assert issubclass(PydUserBack, BaseModel)
    print(f"pydantic field metadata: {PydUserBack.model_fields['email'].description!r}")

    pu = PydUserBack(id="u1", email="ada@example.org")
    print(f"pydantic instance: {pu}")


if __name__ == "__main__":
    main()
