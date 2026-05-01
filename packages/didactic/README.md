# didactic

*A typed-data library for Python on top of [panproto](https://github.com/panproto/panproto).*

[![PyPI](https://img.shields.io/pypi/v/didactic?style=flat-square&color=blue)](https://pypi.org/project/didactic/)
[![Python](https://img.shields.io/pypi/pyversions/didactic?style=flat-square)](https://pypi.org/project/didactic/)
[![License](https://img.shields.io/pypi/l/didactic?style=flat-square&color=green)](https://github.com/panproto/didactic/blob/main/LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/panproto/didactic/ci.yml?branch=main&style=flat-square&label=ci)](https://github.com/panproto/didactic/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-panproto.dev-blue?style=flat-square)](https://panproto.dev/didactic/)

Authoring is class-based and looks like Pydantic. Underneath, every
Model corresponds to a panproto `Theory`, every value to a panproto
`Schema`, and every transformation between Models to a panproto
`Lens`.

This is the core distribution. Three sibling distributions
(`didactic-pydantic`, `didactic-settings`, `didactic-fastapi`)
contribute submodules under `didactic.<name>`.

## Install

didactic targets Python 3.14 and panproto 0.43+.

```sh
pip install didactic
```

## Quickstart

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

## Documentation

The full documentation site is at
[panproto.dev/didactic](https://panproto.dev/didactic/) and
includes a tutorial, task-oriented guides, conceptual background,
and per-symbol API reference. Source is in the workspace `docs/`
directory.

## License

Released under the [MIT License](https://github.com/panproto/didactic/blob/main/LICENSE).
