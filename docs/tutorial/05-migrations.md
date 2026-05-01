# Writing a migration

A migration is a [Lens][didactic.api.Lens] (or
[Iso][didactic.api.Iso]) between two Model versions, registered in a
process-global registry. The loader looks up registered migrations
by structural fingerprint and applies them when reading older
payloads.

## The two versions

Suppose `User` started with a single `name` field, and a later
release split that into `given_name` and `family_name`:

```python
import didactic.api as dx


class UserV1(dx.Model):
    id: str
    name: str


class UserV2(dx.Model):
    id: str
    given_name: str
    family_name: str = ""
```

## The migration

Subclass [Iso][didactic.api.Iso] when the migration is reversible, or
[Lens][didactic.api.Lens] when there is residual information that has
to flow through a complement.

```python
class V1ToV2(dx.Iso[UserV1, UserV2]):
    """Split the legacy `name` field into given and family parts."""

    def forward(self, u: UserV1) -> UserV2:
        first, _, last = u.name.partition(" ")
        return UserV2(id=u.id, given_name=first, family_name=last)

    def backward(self, u: UserV2) -> UserV1:
        return UserV1(
            id=u.id,
            name=f"{u.given_name} {u.family_name}".rstrip(),
        )
```

## Registering and using

```python
dx.register_migration(UserV1, UserV2, V1ToV2())

# from a live UserV1 instance:
v1 = UserV1(id="u1", name="Ada Lovelace")
v2 = dx.migrate(v1, target=UserV2)

# from an older JSON payload:
payload = {"id": "u2", "name": "Grace Hopper"}
v2 = dx.migrate(payload, source=UserV1, target=UserV2)
```

`migrate` walks the registry breadth-first over fingerprints, so a
chain of registered hops applies in order. If no path exists,
`migrate` raises `LookupError` with both fingerprints in the message.

## Verifying the migration

Use [dx.testing.verify_iso][didactic.api.testing.verify_iso] to check
the round-trip law against a Hypothesis strategy:

```python
from hypothesis import strategies as st

dx.testing.verify_iso(
    V1ToV2(),
    st.builds(UserV1, id=st.text(min_size=1), name=st.text()),
)
```

This is the end of the tutorial. The [Guides](../guide/index.md) cover
each topic in more depth, and the [Concepts](../concepts/index.md)
section explains why migrations key on a structural fingerprint of
the Theory rather than the class identity.
