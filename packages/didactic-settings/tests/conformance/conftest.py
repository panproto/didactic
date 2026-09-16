"""Shared fixtures for compose tests.

Defines a small fake didactic schema so the tests exercise the
subpackage without depending on ``BeadConfig``. This is the same
discipline the subpackage uses internally: tests against a generic
``dx.Model`` so they survive the eventual extraction.
"""

from __future__ import annotations

import didactic.api as dx


class FakeNested(dx.Model):
    """Two-field nested model used in tests."""

    value: str = ""
    count: int = 0


class FakeSchema(dx.Model):
    """Small two-level didactic schema used as the compose target."""

    name: str = ""
    paths: dict[str, str] = dx.field(default_factory=dict)
    items: tuple[str, ...] = ()
    nested: dx.Embed[FakeNested] = dx.field(default_factory=FakeNested)
    enabled: bool = False
