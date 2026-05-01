"""Class-level axioms and their construction-time enforcement."""

from didactic.axioms._axiom_enforcement import check_class_axioms
from didactic.axioms._axioms import Axiom, axiom, collect_class_axioms

__all__ = [
    "Axiom",
    "axiom",
    "check_class_axioms",
    "collect_class_axioms",
]
