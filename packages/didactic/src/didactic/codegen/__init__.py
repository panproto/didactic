"""Code generation: emit Models as schema artefacts or source files.

This module is the didactic-shaped facade over panproto's emission
tools. Three entry points:

[didactic.codegen.io][]
    Instance-level parse and emit via panproto's ``IoRegistry`` (50+
    protocol codecs: Avro, JSON Schema, OpenAPI, FHIR, Protobuf,
    Cassandra DDL, BSON, CDDL, Parquet, ...).

[didactic.codegen.source][]
    Source-level parse and emit via panproto's
    ``AstParserRegistry`` (tree-sitter grammars: Rust, TypeScript,
    Python, Go, Java, ...). Includes the de-novo
    ``emit_pretty(model_class, target=...)`` path that renders a
    [Model][didactic.api.Model] class as fresh source.

[didactic.codegen.emitter][]
    The custom emitter framework: register a Python emitter under a
    protocol name and have it dispatch through the same
    [Model.emit_as][didactic.api.Model.emit_as] entry point.

The user-facing convenience method [Model.emit_as][didactic.api.Model.emit_as]
dispatches across all three.

See Also
--------
didactic.Model.emit_as : the single entry point most callers should use.
"""

from __future__ import annotations

from didactic.codegen import io, source
from didactic.codegen._emitter import (
    Emitter,
    IndentWriter,
    emitter,
    list_emitters,
    register_emitter,
)
from didactic.codegen._json_schema import json_schema_of
from didactic.codegen._write import write

__all__ = [
    "Emitter",
    "IndentWriter",
    "emitter",
    "io",
    "json_schema_of",
    "list_emitters",
    "register_emitter",
    "source",
    "write",
]
