"""Tests for the lens skeleton (Mapping / Iso / Lens / composition)."""

import pytest

import didactic.api as dx

# -- a small representative model ----------------------------------------


class User(dx.Model):
    id: str
    email: str
    bio: str = ""


# -- Mapping -------------------------------------------------------------


class LowercaseEmail(dx.Mapping[User, User]):
    """One-way: forward only."""

    def forward(self, u: User) -> User:
        return u.with_(email=u.email.lower())


def test_mapping_call_invokes_forward() -> None:
    u = User(id="u1", email="ALICE@example.com")
    out = LowercaseEmail()(u)
    assert out.email == "alice@example.com"


def test_mapping_records_source_and_target() -> None:
    assert LowercaseEmail.__source__ is User
    assert LowercaseEmail.__target__ is User


def test_mapping_default_forward_raises() -> None:
    class Bad(dx.Mapping[User, User]):
        pass

    with pytest.raises(NotImplementedError):
        Bad().forward(User(id="x", email=""))


# -- Iso ----------------------------------------------------------------


class TrimEmail(dx.Iso[User, User]):
    """Strip whitespace from email; reversible (no information lost)."""

    def forward(self, u: User) -> User:
        return u.with_(email=u.email.strip())

    def backward(self, u: User) -> User:
        return u  # information was zero


def test_iso_forward_and_backward() -> None:
    u = User(id="u1", email="  a@b.c  ")
    iso = TrimEmail()
    after = iso.forward(u)
    assert after.email == "a@b.c"
    assert iso.backward(after) == after


def test_iso_inverse_swaps_directions() -> None:
    iso = TrimEmail()
    inv = iso.inverse()
    u = User(id="u1", email="x")
    assert inv.forward(u) == u
    # double-inverse is the original
    assert inv.inverse() is iso


# -- Lens (general, with complement) ----------------------------------


class TruncateBio(dx.Lens[User, User, str]):
    """Truncate bio to ``n`` chars; complement carries the trimmed tail."""

    def __init__(self, n: int) -> None:
        self.n = n

    def forward(self, u: User, /) -> tuple[User, str]:
        head, tail = u.bio[: self.n], u.bio[self.n :]
        return u.with_(bio=head), tail

    def backward(self, u_after: User, complement: str, /) -> User:
        return u_after.with_(bio=u_after.bio + complement)


def test_lens_round_trip_law() -> None:
    u = User(id="u1", email="a@b.c", bio="this bio is too long")
    L = TruncateBio(8)
    truncated, tail = L.forward(u)
    assert truncated.bio == "this bio"
    assert tail == " is too long"
    # GetPut law: backward(*forward(a)) == a
    assert L.backward(truncated, tail) == u


def test_lens_records_source_target() -> None:
    assert TruncateBio.__source__ is User
    assert TruncateBio.__target__ is User


# -- composition ------------------------------------------------------


def test_mapping_composition_left_to_right() -> None:
    class AddDot(dx.Mapping[User, User]):
        def forward(self, u: User) -> User:
            return u.with_(email=u.email + ".")

    chain = LowercaseEmail() >> AddDot()
    out = chain(User(id="u1", email="ALICE@b.c"))
    assert out.email == "alice@b.c."


def test_iso_composition_via_mapping_protocol() -> None:
    # Iso is a subclass of Mapping, so it composes with Mapping
    class AddPrefix(dx.Mapping[User, User]):
        def forward(self, u: User) -> User:
            return u.with_(email="prefix-" + u.email)

    chain = TrimEmail() >> AddPrefix()
    u = User(id="u1", email="  a  ")
    assert chain(u).email == "prefix-a"


def test_lens_composition_threads_complement() -> None:
    L = TruncateBio(4) >> TruncateBio(2)
    u = User(id="u1", email="x", bio="abcdefgh")
    out, complement = L.forward(u)
    assert out.bio == "ab"
    # backward should reconstruct the original
    assert L.backward(out, complement) == u


# -- identity ---------------------------------------------------------


def test_identity_iso_passes_through() -> None:
    id_user = dx.lens.identity(User)
    u = User(id="u1", email="x")
    assert id_user(u) is u
    assert id_user.backward(u) is u


def test_identity_iso_inverse_is_identity_iso() -> None:
    id_user = dx.lens.identity(User)
    inv = id_user.inverse()
    u = User(id="u1", email="x")
    assert inv(u) is u


# -- @dx.lens decorator -----------------------------------------------


def test_lens_decorator_produces_mapping() -> None:
    @dx.lens(User, User)
    def lowercase(u: User) -> User:
        return u.with_(email=u.email.lower())

    assert isinstance(lowercase, dx.Mapping)
    u = User(id="u1", email="ALICE@b.c")
    assert lowercase(u).email == "alice@b.c"


def test_lens_decorator_compose() -> None:
    @dx.lens(User, User)
    def lowercase(u: User) -> User:
        return u.with_(email=u.email.lower())

    @dx.lens(User, User)
    def append_dot(u: User) -> User:
        return u.with_(email=u.email + ".")

    chain = lowercase >> append_dot
    u = User(id="u1", email="ALICE")
    assert chain(u).email == "alice."


# -- attribute access on the dx.lens namespace -----------------------


def test_iso_inverse_backward_invokes_inner_forward() -> None:
    """``inv.backward(x)`` reaches the inner Iso's ``forward``."""
    iso = TrimEmail()
    inv = iso.inverse()
    u = User(id="u1", email="  pad  ")
    # `inv.backward` is the inner's `forward`, which strips whitespace
    assert inv.backward(u).email == "pad"


def test_iso_default_backward_raises() -> None:
    """An Iso subclass that omits ``backward`` raises NotImplementedError."""

    class HalfIso(dx.Iso[User, User]):
        def forward(self, u: User) -> User:
            return u

    with pytest.raises(NotImplementedError):
        HalfIso().backward(User(id="x", email=""))


def test_lens_default_forward_and_backward_raise() -> None:
    """A Lens subclass without overrides raises ``NotImplementedError``."""

    class _Empty(dx.Lens[User, User]):
        pass

    with pytest.raises(NotImplementedError):
        _Empty().forward(User(id="x", email=""))
    with pytest.raises(NotImplementedError):
        _Empty().backward(User(id="x", email=""), None)


def test_lens_call_dispatches_to_forward() -> None:
    """``Lens.__call__`` is sugar for ``forward``."""
    L = TruncateBio(2)
    u = User(id="u1", email="x", bio="abcdef")
    assert L(u) == L.forward(u)


def test_mapping_rshift_with_non_mapping_returns_notimplemented() -> None:
    """``Mapping >> int`` returns NotImplemented (not a TypeError chain)."""
    out = LowercaseEmail().__rshift__(42)  # type: ignore[arg-type]
    assert out is NotImplemented


def test_lens_rshift_with_non_lens_returns_notimplemented() -> None:
    out = TruncateBio(2).__rshift__(42)  # type: ignore[arg-type]
    assert out is NotImplemented


def test_composed_mapping_repr_contains_both_components() -> None:
    chain = LowercaseEmail() >> LowercaseEmail()
    assert ">>" in repr(chain)


def test_inverse_iso_repr_starts_with_tilde() -> None:
    inv = TrimEmail().inverse()
    assert repr(inv).startswith("~")


def test_composed_lens_repr_contains_both_components() -> None:
    L = TruncateBio(2) >> TruncateBio(1)
    assert ">>" in repr(L)


def test_dx_lens_namespace_exposes_classes_and_helpers() -> None:
    # `dx.lens` is both the decorator function and a namespace with
    # convenience attributes.
    assert dx.lens.Lens is dx.Lens
    assert dx.lens.Iso is dx.Iso
    assert dx.lens.Mapping is dx.Mapping
    assert dx.lens.identity is not None
