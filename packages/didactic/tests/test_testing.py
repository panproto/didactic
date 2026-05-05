"""Tests for the dx.testing helpers (verify_iso, check_lens_laws)."""

import pytest
from hypothesis import strategies as st

import didactic.api as dx

# -- a representative iso & lens --------------------------------------


class User(dx.Model):
    id: str
    bio: str = ""


class IdentityIso(dx.Iso[User, User]):
    """The identity Iso; trivially round-trips."""

    def forward(self, u: User) -> User:
        return u

    def backward(self, u: User) -> User:
        return u


class TruncateBio(dx.Lens[User, User, str]):
    """Truncate bio to ``n`` chars; complement carries the tail."""

    def __init__(self, n: int) -> None:
        self.n = n

    def forward(self, u: User) -> tuple[User, str]:
        head, tail = u.bio[: self.n], u.bio[self.n :]
        return u.with_(bio=head), tail

    def backward(self, u: User, complement: str) -> User:
        return u.with_(bio=u.bio + complement)


users = st.builds(User, id=st.text(max_size=20), bio=st.text(max_size=50))

# -- verify_iso ----------------------------------------------------


def test_verify_iso_passes_for_identity() -> None:
    dx.testing.verify_iso(IdentityIso(), users, max_examples=50)


def test_verify_iso_catches_a_bad_iso() -> None:
    class WrongIso(dx.Iso[User, User]):
        def forward(self, u: User) -> User:
            # mutates bio in a way the inverse won't undo
            return u.with_(bio=u.bio + "!")

        def backward(self, u: User) -> User:
            return u  # forgets to strip the trailing `!`

    with pytest.raises(AssertionError, match="round-trip failed"):
        dx.testing.verify_iso(WrongIso(), users, max_examples=10)


# -- check_lens_laws ------------------------------------------------


def test_check_lens_laws_passes_for_truncate_bio() -> None:
    dx.testing.check_lens_laws(TruncateBio(10), users, max_examples=50)


def test_check_lens_laws_catches_a_bad_lens() -> None:
    class BadLens(dx.Lens[User, User, str]):
        def forward(self, u: User) -> tuple[User, str]:
            # drops the tail without storing it in the complement
            return u.with_(bio=u.bio[:5]), ""

        def backward(self, u: User, complement: str) -> User:
            return u  # cannot reconstruct without the tail

    with pytest.raises(AssertionError, match="GetPut law failed"):
        dx.testing.check_lens_laws(BadLens(), users, max_examples=10)
