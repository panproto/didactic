# didactic

A typed-data library for Python that uses
[panproto](https://github.com/panproto/panproto) as its substrate.
Authoring is class-based and looks like Pydantic. Underneath, every
Model corresponds to a panproto `Theory`, every value to a panproto
`Schema`, and every transformation between Models to a panproto
`Lens`.

```python
import didactic.api as dx


class User(dx.Model):
    """A user record."""

    id: str
    email: str
    display_name: str = ""


u = User(id="u1", email="a@b.c")
u2 = u.with_(display_name="Alice")
```

This is the core distribution. Three sibling distributions
(`didactic-pydantic`, `didactic-settings`, `didactic-fastapi`)
contribute submodules under `didactic.<name>`.

## Install

didactic targets Python 3.14 and panproto 0.42+.

```sh
pip install didactic
```

## Documentation

The full documentation site is at
[https://panproto.dev/didactic/](https://panproto.dev/didactic/)
and includes a tutorial, task-oriented guides, conceptual background,
and per-symbol API reference. Source is in the workspace `docs/`
directory.

## License

MIT.
