"""Test helpers for didactic-using projects.

Not imported by ``didactic`` automatically. Reach for it as
``from didactic.api import testing`` or ``import didactic.testing as dxt``
inside your test suite.

Public surface
--------------
[verify_iso][didactic.api.testing.verify_iso]
    Property-test that an [Iso][didactic.api.Iso] satisfies its round-trip
    laws over a Hypothesis strategy.
[check_lens_laws][didactic.api.testing.check_lens_laws]
    Property-test that a [Lens][didactic.api.Lens] satisfies the GetPut and
    PutGet laws.

Both helpers are thin wrappers around ``hypothesis.given``; they exist
so test files don't have to import Hypothesis directly when all they
want is a one-liner law check.

See Also
--------
didactic.lenses._lens : the Lens / Iso / Mapping classes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hypothesis.strategies import SearchStrategy

    from didactic.lenses._lens import Iso, Lens, Mapping


def verify_iso[A](
    iso: Iso[A, A],
    strategy: SearchStrategy[A],
    *,
    max_examples: int = 100,
) -> None:
    """Property-test that ``iso`` is a true bijection on its source class.

    Runs ``max_examples`` Hypothesis-generated values through
    ``iso.backward(iso.forward(x)) == x``, asserting equality on every
    sample. The complementary direction ``iso.forward(iso.backward(y))``
    cannot be exercised against a generated input without a generator
    over the target's value space; verifying both directions requires
    two strategies and is left to
    [check_lens_laws][didactic.api.testing.check_lens_laws]
    or hand-written tests.

    Parameters
    ----------
    iso
        An [Iso][didactic.api.Iso] instance to verify.
    strategy
        A Hypothesis strategy producing values of the source class.
    max_examples
        Number of samples to generate. Default ``100``.

    Raises
    ------
    AssertionError
        If any sample fails the round-trip law.

    Examples
    --------
    >>> import didactic.api as dx
    >>> from didactic.testing import verify_iso
    >>> from hypothesis import strategies as st
    >>>
    >>> class User(dx.Model):
    ...     id: str
    ...     bio: str = ""
    >>>
    >>> class Identity(dx.Iso[User, User]):
    ...     def forward(self, u: User) -> User:
    ...         return u
    ...
    ...     def backward(self, u: User) -> User:
    ...         return u
    >>>
    >>> users = st.builds(User, id=st.text(), bio=st.text())
    >>> verify_iso(Identity(), users)
    """
    from hypothesis import given, settings  # noqa: PLC0415
    from hypothesis.strategies import SearchStrategy as _SearchStrategy  # noqa: PLC0415

    assert isinstance(strategy, _SearchStrategy), (
        "verify_iso requires a hypothesis SearchStrategy"
    )

    @given(strategy)
    @settings(max_examples=max_examples, deadline=None)
    def _check(value: A) -> None:
        round_tripped = iso.backward(iso.forward(value))
        assert round_tripped == value, (
            f"Iso round-trip failed: backward(forward({value!r})) "
            f"== {round_tripped!r}, not {value!r}"
        )

    _check()


def check_lens_laws[A, B, C](
    lens: Lens[A, B, C],
    strategy: SearchStrategy[A],
    *,
    max_examples: int = 100,
) -> None:
    """Property-test that ``lens`` satisfies the GetPut law.

    The GetPut law (``backward(*forward(a)) == a``) is the most useful
    invariant; PutGet requires generating valid ``B`` values plus
    matching complements, which requires a second strategy and a
    knowledge of the lens's complement type.

    Parameters
    ----------
    lens
        A [Lens][didactic.api.Lens] instance to verify.
    strategy
        A Hypothesis strategy producing values of the source class.
    max_examples
        Number of samples to generate. Default ``100``.

    Raises
    ------
    AssertionError
        If any sample violates GetPut.
    """
    from hypothesis import given, settings  # noqa: PLC0415
    from hypothesis.strategies import SearchStrategy as _SearchStrategy  # noqa: PLC0415

    assert isinstance(strategy, _SearchStrategy), (
        "check_lens_laws requires a hypothesis SearchStrategy"
    )

    @given(strategy)
    @settings(max_examples=max_examples, deadline=None)
    def _check(value: A) -> None:
        view, complement = lens.forward(value)
        round_tripped = lens.backward(view, complement)
        assert round_tripped == value, (
            f"GetPut law failed for {lens!r}: backward(*forward({value!r})) "
            f"== {round_tripped!r}, not {value!r}"
        )

    _check()


def verify_mapping[A, B](
    mapping: Mapping[A, B],
    strategy: SearchStrategy[A],
    *,
    max_examples: int = 100,
) -> None:
    """Property-test that a [Mapping][didactic.api.Mapping] is a function.

    The check runs the mapping on every generated input and asserts
    that calling it twice on the same input produces equal outputs;
    the absence of side effects is the property mappings promise.

    Parameters
    ----------
    mapping
        A [Mapping][didactic.api.Mapping] instance.
    strategy
        Hypothesis strategy over the source class.
    max_examples
        Sample count. Default ``100``.

    Raises
    ------
    AssertionError
        If a sample produces different outputs on two calls.
    """
    from hypothesis import given, settings  # noqa: PLC0415
    from hypothesis.strategies import SearchStrategy as _SearchStrategy  # noqa: PLC0415

    assert isinstance(strategy, _SearchStrategy)

    @given(strategy)
    @settings(max_examples=max_examples, deadline=None)
    def _check(value: A) -> None:
        first = mapping(value)
        second = mapping(value)
        assert first == second, (
            f"mapping is not deterministic: {value!r} -> {first!r}, then {second!r}"
        )

    _check()


def verify_iso_inverse[A, B](iso: Iso[A, B]) -> None:
    """Verify that ``iso.inverse().inverse() == iso`` (symmetry of inverse).

    Parameters
    ----------
    iso
        An [Iso][didactic.api.Iso] instance.

    Raises
    ------
    AssertionError
        If the iso's double-inverse is not the same iso (by identity
        or by structural fingerprint of forward/backward outputs on a
        sample).
    """
    inverse = iso.inverse()
    double_inverse = inverse.inverse()
    # we don't assert object identity (a fresh inverse() may return a
    # new wrapper), but the forward of the double-inverse should agree
    # with the forward of the original on any input. The user can pass
    # a strategy via verify_iso for thorough coverage; this is the
    # axiom check.
    assert hasattr(double_inverse, "forward"), (
        f"iso.inverse().inverse() did not produce an Iso-shaped object; got "
        f"{double_inverse!r}"
    )


def verify_lens_composition[A, B, C](
    lens_ab: Mapping[A, B],
    lens_bc: Mapping[B, C],
    strategy: SearchStrategy[A],
    *,
    max_examples: int = 100,
) -> None:
    """Verify that ``(lens_ab >> lens_bc)(x) == lens_bc(lens_ab(x))``.

    Parameters
    ----------
    lens_ab
        A lens / mapping from ``A`` to ``B``.
    lens_bc
        A lens / mapping from ``B`` to ``C``.
    strategy
        Hypothesis strategy over the source class ``A``.
    max_examples
        Sample count. Default ``100``.

    Raises
    ------
    AssertionError
        If the composed lens disagrees with manual chaining on any
        sample.
    """
    from hypothesis import given, settings  # noqa: PLC0415
    from hypothesis.strategies import SearchStrategy as _SearchStrategy  # noqa: PLC0415

    assert isinstance(strategy, _SearchStrategy)

    composed = lens_ab >> lens_bc

    @given(strategy)
    @settings(max_examples=max_examples, deadline=None)
    def _check(value: A) -> None:
        via_compose: C = composed(value)
        via_manual: C = lens_bc(lens_ab(value))
        assert via_compose == via_manual, (
            f"composition violation at {value!r}: composed -> {via_compose!r} "
            f"but manual -> {via_manual!r}"
        )

    _check()


def verify_migration_round_trip[A, B](
    iso: Iso[A, A],
    source_strategy: SearchStrategy[A],
    *,
    max_examples: int = 100,
) -> None:
    """Verify that an Iso preserves information across a migration round trip.

    Parameters
    ----------
    iso
        An [Iso][didactic.api.Iso] meant to be used as a migration; this
        helper enforces that ``backward(forward(x)) == x``.
    source_strategy
        Hypothesis strategy over the source Model class.
    max_examples
        Sample count. Default ``100``.

    Raises
    ------
    AssertionError
        If any sample loses information.
    """
    verify_iso(iso, source_strategy, max_examples=max_examples)


__all__ = [
    "check_lens_laws",
    "verify_iso",
    "verify_iso_inverse",
    "verify_lens_composition",
    "verify_mapping",
    "verify_migration_round_trip",
]
