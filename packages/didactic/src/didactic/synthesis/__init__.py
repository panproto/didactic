"""Inbound synthesis: panproto Theory specs back into didactic Models.

The faithful inverse of [build_theory_spec][didactic.theory._theory.build_theory_spec].
See [didactic.synthesis._synthesis][] for the reconstruction strategy and
its honest limitations.
"""

from didactic.synthesis._synthesis import (
    model_from_spec,
    model_from_theory,
    models_from_specs,
)

__all__ = [
    "model_from_spec",
    "model_from_theory",
    "models_from_specs",
]
