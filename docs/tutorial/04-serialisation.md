# Serialisation

Every Model exposes four serialisation entry points:

| operation | direction |
| --- | --- |
| [model_dump][didactic.api.Model.model_dump] | Model -> `dict` |
| [model_dump_json][didactic.api.Model.model_dump_json] | Model -> JSON `str` |
| [model_validate][didactic.api.Model.model_validate] | `dict` -> Model |
| [model_validate_json][didactic.api.Model.model_validate_json] | JSON `str` -> Model |

`model_dump` is the load-bearing one; `model_dump_json` is a thin
wrapper that adds JSON encoding for non-natively-JSON types.

## model_dump options

```python
import didactic.api as dx


class User(dx.Model):
    id: str
    email: str
    nickname: str = ""
    legacy_id: str | None = None


u = User(id="u1", email="ada@example.org")

u.model_dump()
# {'id': 'u1', 'email': 'ada@example.org', 'nickname': '', 'legacy_id': None}

u.model_dump(include={"id", "email"})
# {'id': 'u1', 'email': 'ada@example.org'}

u.model_dump(exclude={"nickname"})
# {'id': 'u1', 'email': 'ada@example.org', 'legacy_id': None}

u.model_dump(exclude_none=True)
# {'id': 'u1', 'email': 'ada@example.org', 'nickname': ''}

u.model_dump(exclude_defaults=True)
# {'id': 'u1', 'email': 'ada@example.org'}
```

`by_alias=True` substitutes each field's
[alias][didactic.api.field] when one is set:

```python
class User(dx.Model):
    user_id: str = dx.field(alias="userId")
    email: str

User(user_id="u1", email="a@b").model_dump(by_alias=True)
# {'userId': 'u1', 'email': 'a@b'}
```

## JSON encoding

`model_dump_json` converts non-natively-JSON values (`datetime`,
`Decimal`, `UUID`, `bytes`, `frozenset`) to JSON-friendly forms.
`model_validate_json` reverses the same conversion. The two are
inverse on every supported type.

```python
import datetime as _dt


class Event(dx.Model):
    when: _dt.datetime


e = Event(when=_dt.datetime(2024, 1, 1, 12, 0))
text = e.model_dump_json()
# '{"when": "2024-01-01T12:00:00"}'

back = Event.model_validate_json(text)
back == e  # True
```

## JSON Schema

`Model.model_json_schema()` produces a Draft 2020-12 JSON Schema
document. Field descriptions, examples, deprecation flags, and
`annotated-types` constraints all flow through.

```python
class User(dx.Model):
    """A user record."""

    id: str
    email: str = dx.field(description="primary contact")


User.model_json_schema()
# {
#   '$schema': 'https://json-schema.org/draft/2020-12/schema',
#   'title': 'User',
#   'description': 'A user record.',
#   'type': 'object',
#   'properties': {
#     'id': {'type': 'string'},
#     'email': {'type': 'string', 'description': 'primary contact'},
#   },
#   'required': ['id', 'email'],
# }
```

The same Model can also be emitted as Avro, OpenAPI, Protobuf, and
the other schema formats panproto supports. See
[Guides > Code generation](../guide/codegen.md).

[Next: writing a migration](05-migrations.md).
