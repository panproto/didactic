"""Class-level ``__axioms__`` collection.

Models can declare a list of axioms (panproto-Expr-shaped constraint
strings) through a class-level ``__axioms__`` attribute. The metaclass
collects these into ``cls.__class_axioms__`` so the theory builder can
emit them as Theory equations.

Examples
--------
>>> import didactic.api as dx
>>>
>>> class Pitched(dx.Model):
...     pitches: tuple[int, ...]
...
...     __axioms__ = [
...         dx.axiom("len(pitches) > 0", message="must be non-empty"),
...         dx.axiom("forall p in pitches: 0 <= p <= 127"),
...     ]
>>>
>>> Pitched.__class_axioms__
(Axiom(expr='len(pitches) > 0', ...), Axiom(expr='0 <= p <= 127', ...))

Notes
-----
The expression strings are not yet evaluated against panproto's Expr
parser; that wires up once the panproto runtime is available.
``__axioms__`` is the authoring surface; ``__class_axioms__`` is the
metaclass-collected canonical form (a tuple of ``Axiom`` records).

See Also
--------
didactic.models._meta : the metaclass that collects __axioms__.
didactic.theory._theory : the bridge that emits axioms as Theory equations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Axiom:
    """A class-level axiom expressed as a string.

    Parameters
    ----------
    expr
        The axiom expression in panproto-Expr-shaped surface syntax.
    message
        Optional human-readable message surfaced in
        [didactic.api.ValidationError][] when the axiom fails.
    name
        Optional identifier; defaults to a generated label.

    See Also
    --------
    axiom : the convenience constructor.
    """

    expr: str
    message: str | None = None
    name: str | None = None


def axiom(expr: str, *, message: str | None = None, name: str | None = None) -> Axiom:
    """Construct an [Axiom][didactic.axioms._axioms.Axiom] for a class's ``__axioms__``.

    Parameters
    ----------
    expr
        The axiom expression. Free variables are field names of the
        enclosing Model.
    message
        Optional human-readable explanation surfaced when the axiom
        fails validation.
    name
        Optional identifier. Defaults to the metaclass synthesising one
        from the expression text.

    Returns
    -------
    Axiom
        A frozen Axiom record. Place it in the class's ``__axioms__``
        list.

    Examples
    --------
    >>> import didactic.api as dx
    >>> class Pitched(dx.Model):
    ...     pitches: tuple[int, ...]
    ...     __axioms__ = [
    ...         dx.axiom("len(pitches) > 0", message="must be non-empty"),
    ...     ]
    """
    return Axiom(expr=expr, message=message, name=name)


def collect_class_axioms(cls: type) -> tuple[Axiom, ...]:
    """Collect all class-level ``__axioms__`` lists across MRO.

    Parameters
    ----------
    cls
        A class whose MRO will be walked.

    Returns
    -------
    tuple
        All axioms found, base classes first, in declaration order.
        Duplicates by ``expr`` are kept (a derived class may legitimately
        re-state a parent's axiom).
    """
    found: list[Axiom] = []
    for klass in reversed(cls.__mro__):
        raw = klass.__dict__.get("__axioms__")
        if raw is None:
            continue
        for entry in raw:
            if isinstance(entry, Axiom):
                found.append(entry)
            elif isinstance(entry, str):
                # also accept bare strings as a convenience
                found.append(Axiom(expr=entry))
            else:
                msg = (
                    f"{klass.__name__}.__axioms__ entries must be "
                    f"didactic.Axiom or str; got {type(entry).__name__}"
                )
                raise TypeError(msg)
    return tuple(found)


__all__ = [
    "Axiom",
    "axiom",
    "collect_class_axioms",
]
