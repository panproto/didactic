# Tutorial

This tutorial is a single thread that builds a small application
end-to-end. The five chapters cover:

1. [First model](01-first-model.md): defining a class, instantiating
   it, and reading its fields.
2. [Fields and types](02-fields.md): defaults, descriptions, the
   `dx.field(...)` metadata constructor, and the built-in scalar
   types.
3. [Validation](03-validation.md): per-field validators, class-level
   axioms, and the shape of a `ValidationError`.
4. [Serialisation](04-serialisation.md): `model_dump`, `model_dump_json`,
   the inverse `model_validate` and `model_validate_json` paths,
   plus JSON Schema export.
5. [Writing a migration](05-migrations.md): defining a `Lens` between
   two versions of a Model and registering it for use by
   `dx.migrate`.

By the end you will have a working set of Models, a registered
migration, a JSON Schema artefact, and a feel for the day-to-day
operations didactic supports.

The tutorial assumes Python 3.14 and `pip install didactic`.
