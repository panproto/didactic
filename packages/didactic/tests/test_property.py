"""Property-based round-trip tests using Hypothesis.

Each test takes the form: generate values for a model's fields, build
the model, and assert that one of the round-trips
(dict / JSON / pickle / with_) is the identity.
"""

import pickle
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID  # noqa: TC003 - used at runtime in Scalar's annotation

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

import didactic.api as dx


class Scalar(dx.Model):
    """All scalar field types in a single model."""

    s: str
    i: int
    f: float
    b: bool
    d: Decimal
    when: datetime
    day: date
    uid: UUID


class Containers(dx.Model):
    """Containers and optional fields."""

    tags: tuple[str, ...]
    counts: dict[str, int]
    flags: frozenset[str]
    maybe: int | None


# -- strategies -----------------------------------------------------------

decimal_st = st.decimals(
    allow_nan=False,
    allow_infinity=False,
    places=4,
    min_value=-1_000_000,
    max_value=1_000_000,
).map(Decimal)

datetime_st = st.datetimes(
    min_value=datetime(1970, 1, 1),
    max_value=datetime(2100, 1, 1),
)

date_st = st.dates(
    min_value=date(1970, 1, 1),
    max_value=date(2100, 1, 1),
)

uuid_st = st.uuids()

# floats: exclude NaN (NaN != NaN breaks equality round-trips)
float_st = st.floats(
    allow_nan=False,
    allow_infinity=False,
    width=64,
)


@st.composite
def scalar_models(draw: st.DrawFn) -> Scalar:
    return Scalar(
        s=draw(st.text(max_size=50)),
        i=draw(st.integers(min_value=-(2**31), max_value=2**31 - 1)),
        f=draw(float_st),
        b=draw(st.booleans()),
        d=draw(decimal_st),
        when=draw(datetime_st),
        day=draw(date_st),
        uid=draw(uuid_st),
    )


@st.composite
def container_models(draw: st.DrawFn) -> Containers:
    return Containers(
        tags=tuple(draw(st.lists(st.text(max_size=20), max_size=10))),
        counts=draw(st.dictionaries(st.text(max_size=10), st.integers(), max_size=10)),
        flags=frozenset(draw(st.sets(st.text(max_size=10), max_size=10))),
        maybe=draw(st.one_of(st.none(), st.integers())),
    )


# -- round-trip properties ------------------------------------------------

# class-creation in hypothesis test harness can vary; keep deadline lenient
SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


@given(scalar_models())
@SETTINGS
def test_scalar_dict_round_trip(m: Scalar) -> None:
    payload = m.model_dump()
    m2 = Scalar.model_validate(payload)
    assert m == m2


@given(scalar_models())
@SETTINGS
def test_scalar_json_round_trip(m: Scalar) -> None:
    raw = m.model_dump_json()
    m2 = Scalar.model_validate_json(raw)
    assert m == m2


@given(scalar_models())
@SETTINGS
def test_scalar_pickle_round_trip(m: Scalar) -> None:
    blob = pickle.dumps(m)
    m2 = pickle.loads(blob)
    assert m == m2
    assert hash(m) == hash(m2)


@given(container_models())
@SETTINGS
def test_container_dict_round_trip(m: Containers) -> None:
    payload = m.model_dump()
    m2 = Containers.model_validate(payload)
    assert m == m2


@given(container_models())
@SETTINGS
def test_container_json_round_trip(m: Containers) -> None:
    raw = m.model_dump_json()
    m2 = Containers.model_validate_json(raw)
    assert m == m2


@given(container_models())
@SETTINGS
def test_container_pickle_round_trip(m: Containers) -> None:
    blob = pickle.dumps(m)
    m2 = pickle.loads(blob)
    assert m == m2


@given(scalar_models(), st.text(max_size=50))
@SETTINGS
def test_with_replaces_one_field(m: Scalar, new_s: str) -> None:
    assume(new_s != m.s)
    m2 = m.with_(s=new_s)
    assert m2.s == new_s
    # other fields untouched
    assert m2.i == m.i
    assert m2.b == m.b
    # original still has the old value (immutability)
    assert m.s != new_s
