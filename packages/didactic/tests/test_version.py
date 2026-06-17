"""The runtime ``__version__`` of each distribution matches its metadata.

Every distribution hand-maintains a module-level ``__version__`` next to
the version in its ``pyproject.toml``. The four ship in lockstep, so a
release that bumps the packaging version must bump the constant too.
This guards the drift where the two fall out of step.
"""

from __future__ import annotations

from importlib.metadata import version

import pytest

import didactic.api
import didactic.fastapi
import didactic.pydantic
import didactic.settings

# (declared constant, distribution name) for every shipped package.
_DECLARED_VERSIONS: list[tuple[str, str]] = [
    (didactic.api.__version__, "didactic"),
    (didactic.pydantic.__version__, "didactic-pydantic"),
    (didactic.settings.__version__, "didactic-settings"),
    (didactic.fastapi.__version__, "didactic-fastapi"),
]


@pytest.mark.parametrize(("declared", "distribution"), _DECLARED_VERSIONS)
def test_runtime_version_matches_metadata(declared: str, distribution: str) -> None:
    """The ``__version__`` constant equals the installed package version."""
    assert declared == version(distribution)


def test_all_distributions_share_one_version() -> None:
    """The four distributions ship in lockstep at a single version."""
    declared = {v for v, _ in _DECLARED_VERSIONS}
    assert len(declared) == 1
