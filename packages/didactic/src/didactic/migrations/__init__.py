"""Schema migrations: registry, fingerprints, synthesis, diff."""

from didactic.migrations._diff import classify_change, diff, is_breaking_change
from didactic.migrations._fingerprint import (
    canonical_json_bytes,
    fingerprint,
    structural_fingerprint,
    structural_spec,
)
from didactic.migrations._migrations import (
    clear_registry,
    load_registry,
    lookup_migration,
    migrate,
    register_migration,
    registered_fingerprints,
    save_registry,
)
from didactic.migrations._synthesis import SynthesisResult, synthesise_migration

__all__ = [
    "SynthesisResult",
    "canonical_json_bytes",
    "classify_change",
    "clear_registry",
    "diff",
    "fingerprint",
    "is_breaking_change",
    "load_registry",
    "lookup_migration",
    "migrate",
    "register_migration",
    "registered_fingerprints",
    "save_registry",
    "structural_fingerprint",
    "structural_spec",
    "synthesise_migration",
]
