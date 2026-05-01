# Examples

Runnable end-to-end snippets. Each file is self-contained and can be
executed directly:

```bash
uv run python examples/01_basic_model.py
```

| File | Demonstrates |
| ---- | ------------ |
| `01_basic_model.py` | A Model definition, instantiation, JSON round-trip, immutability |
| `02_migration.py` | Registering an Iso and migrating a payload |
| `03_lens.py` | Defining an Iso and verifying its laws with Hypothesis |
| `04_pydantic_interop.py` | Bidirectional Pydantic adapter via `didactic-pydantic` |
