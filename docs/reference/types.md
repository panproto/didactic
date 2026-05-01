# Constrained scalar types

The constrained scalars under `didactic.types`.

::: didactic.types._types_lib.SecretStr

The remaining members of `didactic.types` are annotation aliases:

| name | shape |
| --- | --- |
| `EmailStr` | `Annotated[str, _StringPattern(<email regex>, "email")]` |
| `HttpUrl` | `Annotated[str, _StringPattern(<http url regex>, "http_url")]` |
| `Json[T]` | `Annotated[str, _JsonOf(inner=T)]` |

Use them as drop-in field annotations:

```python
from didactic.types import EmailStr, HttpUrl, SecretStr


class User(dx.Model):
    email: EmailStr
    homepage: HttpUrl | None = None
    api_key: SecretStr
```
