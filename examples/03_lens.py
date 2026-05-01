"""Define an Iso, use it as a callable, and verify its laws.

Demonstrates ``dx.Iso`` plus ``dx.testing.verify_iso``. The example
uses a field-swap iso because that round-trips exactly under any
sample, which makes it well-suited to a property-test demonstration;
real-world conversions like Celsius/Fahrenheit are isos in theory but
break ``backward(forward(x)) == x`` under floating-point rounding.
"""

from __future__ import annotations

from hypothesis import strategies as st

import didactic.api as dx


class FirstLast(dx.Model):
    """A name with given-first ordering."""

    given: str
    family: str


class LastFirst(dx.Model):
    """A name with family-first ordering (e.g. for a directory listing)."""

    family: str
    given: str


class SwapNameOrder(dx.Iso[FirstLast, LastFirst]):
    """A field-swap iso: round-trips exactly because no information is lost."""

    def forward(self, n: FirstLast) -> LastFirst:
        return LastFirst(family=n.family, given=n.given)

    def backward(self, n: LastFirst) -> FirstLast:
        return FirstLast(given=n.given, family=n.family)


def main() -> None:
    """Run a sample conversion and verify the iso laws."""
    iso = SwapNameOrder()
    n = FirstLast(given="Ada", family="Lovelace")
    print(f"{n} -> {iso(n)}")

    rt = iso.backward(iso.forward(n))
    print(f"round trip: {n} -> {rt}")
    assert rt == n

    # verify the iso laws against a Hypothesis strategy. ``verify_iso``
    # checks ``backward(forward(x)) == x`` on samples drawn from the
    # source class's value space.
    source_strategy = st.builds(
        FirstLast,
        given=st.text(min_size=0, max_size=20),
        family=st.text(min_size=0, max_size=20),
    )
    dx.testing.verify_iso(iso, source_strategy)
    print("iso laws verified")


if __name__ == "__main__":
    main()
