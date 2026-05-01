"""Lenses, isomorphisms, mappings, dependent lenses, and law fixtures."""

from didactic.lenses import _testing as testing
from didactic.lenses._dependent_lens import DependentLens
from didactic.lenses._lens import Iso, Lens, Mapping, identity
from didactic.lenses._lens import lens as lens

__all__ = [
    "DependentLens",
    "Iso",
    "Lens",
    "Mapping",
    "identity",
    "lens",
    "testing",
]
