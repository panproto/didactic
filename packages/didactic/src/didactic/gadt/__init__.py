"""Generalized algebraic theories and indexed Model fields."""

from didactic.gadt._ast import (
    App,
    Branch,
    Case,
    Hole,
    Let,
    SortExpr,
    Term,
    Var,
    hole,
    term_from_spec,
)
from didactic.gadt._declarations import (
    GADT,
    Equation,
    Family,
    Motive,
    Operation,
    Parameter,
)
from didactic.gadt._errors import GADTDeclarationError, GADTReductionError
from didactic.gadt._indexed import IndexedBy, Universe, indexed_by
from didactic.gadt._telescope import (
    Body,
    Implicit,
    InputSpec,
    Sort,
    SortSpec,
    let,
    match,
)

__all__ = [
    "GADT",
    "App",
    "Body",
    "Branch",
    "Case",
    "Equation",
    "Family",
    "GADTDeclarationError",
    "GADTReductionError",
    "Hole",
    "Implicit",
    "IndexedBy",
    "InputSpec",
    "Let",
    "Motive",
    "Operation",
    "Parameter",
    "Sort",
    "SortExpr",
    "SortSpec",
    "Term",
    "Universe",
    "Var",
    "hole",
    "indexed_by",
    "let",
    "match",
    "term_from_spec",
]
