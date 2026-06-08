"""Lenses, isomorphisms, mappings, dependent lenses, and law fixtures."""

from didactic.lenses import _testing as testing
from didactic.lenses._dependent_lens import DependentLens
from didactic.lenses._lens import Iso, Lens, Mapping, identity
from didactic.lenses._lens import lens as lens
from didactic.lenses._morphisms import (
    Correspondence,
    best_correspondence,
    find_correspondences,
)

__all__ = [
    "Correspondence",
    "DependentLens",
    "Iso",
    "Lens",
    "Mapping",
    "best_correspondence",
    "find_correspondences",
    "identity",
    "lens",
    "testing",
]
