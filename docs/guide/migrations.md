# Migrations

A migration is a [Lens][didactic.api.Lens] (or
[Iso][didactic.api.Iso]) between two Model classes, registered in the
process-global migration registry. When the loader sees a payload
shaped like an older Model, it consults the registry and applies the
chain of migrations to bring the payload to the target shape.

## Registering a migration

```python
import didactic.api as dx


class UserV1(dx.Model):
    id: str
    name: str


class UserV2(dx.Model):
    id: str
    given_name: str
    family_name: str = ""


class V1ToV2(dx.Iso[UserV1, UserV2]):
    def forward(self, u: UserV1) -> UserV2:
        first, _, last = u.name.partition(" ")
        return UserV2(id=u.id, given_name=first, family_name=last)

    def backward(self, u: UserV2) -> UserV1:
        return UserV1(id=u.id, name=f"{u.given_name} {u.family_name}".rstrip())


dx.register_migration(UserV1, UserV2, V1ToV2())
```

## Applying a migration

```python
v1 = UserV1(id="u1", name="Ada Lovelace")
v2 = dx.migrate(v1, target=UserV2)
# UserV2(id='u1', given_name='Ada', family_name='Lovelace')
```

If `payload` is a dict (e.g. just deserialised from JSON), pass `source=`:

```python
payload = {"id": "u1", "name": "Ada Lovelace"}
v2 = dx.migrate(payload, source=UserV1, target=UserV2)
```

## Multi-hop migrations

Register intermediate hops; `migrate` walks the graph breadth-first:

```python
class UserV3(dx.Model):
    id: str
    given_name: str
    family_name: str = ""
    display_name: str = ""


class V2ToV3(dx.Iso[UserV2, UserV3]):
    ...


dx.register_migration(UserV1, UserV2, V1ToV2())
dx.register_migration(UserV2, UserV3, V2ToV3())

v3 = dx.migrate(UserV1(id="u1", name="Ada"), target=UserV3)
```

## Structural fingerprints

The registry keys on a **structural fingerprint** of each Model's
spec, with the class display name normalised. Two structurally
identical Models share one entry, regardless of their class names. So
if a library renames `User` to `Account` while keeping the fields the
same, the existing migrations keep working.

## Persistence

The registry is process-global and in-memory by default. To checkpoint
a registry to disk for auditing or diagnostic purposes:

```python
dx.save_registry("registry.json")
# ... later, in another process, after re-running the register_migration
# calls ...
confirmed = dx.load_registry("registry.json")
```

`load_registry` does not re-bind lenses (Python callables don't survive
a process boundary); it confirms how many of the on-disk records have
matching in-memory entries. A smaller-than-expected number signals a
migration module wasn't imported.

## See also

- [Migrations reference](../reference/migrations.md) for the full API.
- [Lenses](lenses.md) for the underlying Lens/Iso/Mapping types.
