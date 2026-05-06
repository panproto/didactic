"""Validation errors and the ``@validates`` decorator.

This module defines the user-facing validation surface:
[ValidationError][didactic.api.ValidationError] (raised when construction or
mutation fails), the per-issue [ValidationErrorEntry][didactic.api.ValidationErrorEntry]
record, and the [validates][didactic.api.validates] decorator for Python-side
field validators that supplement (but do not replace) Theory axioms.

Notes
-----
``@validates``-decorated methods live on the Python side only: they are
**not** lifted into the panproto Theory. Constraints expressed as
``Annotated[T, ...]`` metadata or as ``__axioms__`` *are* lifted; choose
the axiom path when you want the constraint to travel cross-language with
the Theory.

See Also
--------
didactic.fields._fields : the field-spec layer that calls into validators.
didactic.models._meta : the metaclass that records validators on the class.
"""

# Stamps ``__didactic_validator__`` onto a function; pyright won't
# let arbitrary attribute assignment on a ``FunctionType``.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from didactic.types._typing import FieldValue


@dataclass(frozen=True, slots=True)
class ValidationErrorEntry:
    """A single validation failure.

    Parameters
    ----------
    loc
        Path through the schema where the failure was detected, e.g.
        ``("orders", 2, "shipping_address", "postal_code")``. Empty tuple
        means "the model itself".
    type
        Error category. One of ``"type_error"``, ``"axiom_violation"``,
        ``"missing_required"``, ``"extra_field"``, ``"converter_error"``,
        ``"validator_error"``, or a panproto-side identifier.
    msg
        Human-readable description.
    axiom
        The panproto-Expr term that failed, when applicable. ``None`` for
        non-axiom failures.
    vertex_id
        The schema vertex id where the violation lives, when known.
    """

    loc: tuple[str | int, ...]
    type: str
    msg: str
    axiom: str | None = None
    vertex_id: str | None = None


@dataclass(slots=True)
class ValidationError(Exception):
    """One or more validation failures, surfaced as a single exception.

    didactic collects all failures during construction or mutation and
    raises them together (no fail-fast). This mirrors Pydantic's behaviour
    so users who grep "for the list of errors" find one.

    Parameters
    ----------
    entries
        The individual failures.
    model
        The model class that failed validation. ``None`` when the failure
        precedes class identification (e.g. discriminated-union dispatch).

    See Also
    --------
    ValidationErrorEntry : the per-issue record.
    """

    entries: tuple[ValidationErrorEntry, ...]
    model: type | None = field(default=None)

    def __str__(self) -> str:
        """Render every entry on its own line."""
        cls_name = self.model.__name__ if self.model is not None else "<unknown>"
        head = f"{len(self.entries)} validation error(s) for {cls_name}"
        body = "\n".join(
            f"  {'.'.join(str(p) for p in e.loc) or '<root>'}: {e.msg} [{e.type}]"
            for e in self.entries
        )
        return f"{head}\n{body}" if body else head


def validates(
    *field_names: str, mode: str = "after"
) -> Callable[
    [Callable[..., FieldValue]],
    Callable[..., FieldValue],
]:
    """Mark a class method as a Python-side validator for one or more fields.

    Parameters
    ----------
    *field_names
        Names of the fields this validator applies to. At least one is required.
    mode
        Either ``"before"`` (run before type validation, may convert) or
        ``"after"`` (run after, receives the typed value).

    Returns
    -------
    Callable
        A decorator that tags the wrapped method for the metaclass to
        register on the field spec.

    Notes
    -----
    Validators are deliberately *not* lifted into the Theory; for
    cross-language constraints, use ``__axioms__`` or ``Annotated[T, ...]``
    metadata instead.

    Examples
    --------
    >>> import didactic.api as dx
    >>> class User(dx.Model):
    ...     email: str
    ...
    ...     @dx.validates("email")
    ...     @classmethod
    ...     def _email_lower(cls, v: str) -> str:
    ...         return v.lower()
    """
    if not field_names:
        msg = "@validates(...) requires at least one field name"
        raise TypeError(msg)
    if mode not in {"before", "after"}:
        msg = f"validates(mode=...) must be 'before' or 'after', got {mode!r}"
        raise ValueError(msg)

    def decorator(
        fn: Callable[..., FieldValue],
    ) -> Callable[..., FieldValue]:
        # Mark the function so the metaclass can find it. ``setattr``
        # writes through the function-object's ``__dict__`` without
        # tripping pyright's narrowed FunctionType view.
        setattr(  # noqa: B010
            fn,
            "__didactic_validator__",
            {"fields": field_names, "mode": mode},
        )
        return fn

    return decorator


def model_validator(
    *, mode: str = "after"
) -> Callable[[Callable[..., object]], Callable[..., object]]:
    """Mark a class method as a class-level validator over the whole instance.

    Class-level validators run *after* every per-field validator and
    every ``__axioms__`` check have already passed. The method
    receives the constructed instance and may ``raise ValueError`` /
    ``raise TypeError`` to reject it; the failure surfaces as a
    ``ValidationError`` entry with ``type="validator_error"`` and an
    empty ``loc`` (i.e. ``loc=()`` -- the failure spans the whole
    model, not any single field).

    Use this for cross-field invariants that don't fit a single-field
    ``@validates`` and that aren't expressible in the
    ``__axioms__`` surface syntax. Pydantic users will recognise the
    shape: this is the rough equivalent of Pydantic v2's
    ``@model_validator(mode="after")``.

    Parameters
    ----------
    mode
        Currently only ``"after"`` is supported. ``"before"`` is
        reserved for a future pre-construction hook.

    Returns
    -------
    Callable
        A decorator that tags the wrapped method for the metaclass to
        register on the class.

    Examples
    --------
    >>> import didactic.api as dx
    >>> class Rules(dx.Model):
    ...     binary_rules: tuple[str, ...]
    ...     binary_weights: tuple[float, ...] | None = None
    ...
    ...     @dx.model_validator()
    ...     def _check_lengths(self) -> "Rules":
    ...         if self.binary_weights is not None and (
    ...             len(self.binary_weights) != len(self.binary_rules)
    ...         ):
    ...             raise ValueError(
    ...                 "binary_weights length must match binary_rules length"
    ...             )
    ...         return self
    """
    if mode != "after":
        msg = f"model_validator(mode=...) currently only accepts 'after'; got {mode!r}"
        raise ValueError(msg)

    def decorator(fn: Callable[..., object]) -> Callable[..., object]:
        setattr(  # noqa: B010
            fn,
            "__didactic_model_validator__",
            {"mode": mode},
        )
        return fn

    return decorator


__all__ = [
    "ValidationError",
    "ValidationErrorEntry",
    "model_validator",
    "validates",
]
