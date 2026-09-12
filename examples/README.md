# Examples

Each program in this directory runs independently from the repository root:

```sh
uv run python examples/01_basic_model.py
```

| File | Demonstrates |
| --- | --- |
| [`01_basic_model.py`](01_basic_model.py) | model definition, JSON round trip, and immutable updates |
| [`02_migration.py`](02_migration.py) | migration registration and execution |
| [`03_lens.py`](03_lens.py) | an isomorphism and its property-based law checks |
| [`04_pydantic_interop.py`](04_pydantic_interop.py) | conversion in both directions between Pydantic and Didactic |

The fourth program requires the `didactic-pydantic` workspace package. Install
all workspace packages and extras with `uv sync --all-packages --all-extras`.
