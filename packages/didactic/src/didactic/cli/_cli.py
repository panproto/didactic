# ``check breaking`` iterates a panproto compat report whose
# ``.breaking`` shape is a ``JsonValue`` union; pyright can't narrow
# the iteration target without per-branch ``isinstance``. Tracked in
# panproto/didactic#1.
"""``didactic`` CLI front-end.

Subcommands
-----------
``didactic schema show <module:Class>``
    Print the Theory spec, fingerprint, and JSON Schema.
``didactic registry list``
    Print every registered migration's source/target fingerprints.
``didactic emit <module:Class> --target <name> [--out <path>]``
    Emit a Model under a target.
``didactic targets``
    List every available emit target (custom + IoRegistry + grammars).
``didactic check breaking <old> <new>``
    Diff two Models and exit non-zero on a breaking change.
``didactic version``
    Print didactic and panproto versions.

Run ``didactic --help`` for the auto-generated help text.

See Also
--------
didactic.codegen : the emission machinery the CLI dispatches to.
didactic.diff : the diff / classify helpers.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from didactic.models._model import Model


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``didactic`` console script.

    Parameters
    ----------
    argv
        Argument list. ``None`` reads from ``sys.argv[1:]``.

    Returns
    -------
    int
        Exit status; ``0`` on success, ``1`` on user error, ``2`` on
        breaking-change detection.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.subcommand is None:
        parser.print_help()
        return 1
    handler = _SUBCOMMANDS[args.subcommand]
    return handler(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="didactic",
        description="didactic: Pydantic-class API on top of panproto.",
    )
    sub = parser.add_subparsers(dest="subcommand")

    p_schema = sub.add_parser("schema", help="inspect a Model's Theory")
    p_schema_sub = p_schema.add_subparsers(dest="schema_action")
    p_schema_show = p_schema_sub.add_parser("show", help="print Theory and JSON Schema")
    p_schema_show.add_argument("model", help="`module.path:ClassName`")

    p_reg = sub.add_parser("registry", help="inspect the migration registry")
    p_reg_sub = p_reg.add_subparsers(dest="registry_action")
    p_reg_sub.add_parser("list", help="list every registered (source_fp, target_fp)")

    p_emit = sub.add_parser("emit", help="emit a Model under a target")
    p_emit.add_argument("model", help="`module.path:ClassName`")
    p_emit.add_argument("--target", required=True, help="target name")
    p_emit.add_argument("--out", default="-", help="output path; '-' for stdout")

    sub.add_parser("targets", help="list every available emit target")

    p_check = sub.add_parser("check", help="diagnostic checks")
    p_check_sub = p_check.add_subparsers(dest="check_action")
    p_check_breaking = p_check_sub.add_parser(
        "breaking",
        help="diff two Models and exit on breaking changes",
    )
    p_check_breaking.add_argument("old", help="`module.path:ClassName`")
    p_check_breaking.add_argument("new", help="`module.path:ClassName`")

    sub.add_parser("version", help="print didactic and panproto versions")

    return parser


# -- subcommand handlers ----------------------------------------------


def _resolve_model(spec: str) -> type[Model]:
    """Resolve ``module.path:ClassName`` to a Model class."""
    if ":" not in spec:
        msg = f"expected `module.path:ClassName`, got {spec!r}"
        raise ValueError(msg)
    mod_name, cls_name = spec.split(":", 1)
    mod = importlib.import_module(mod_name)
    cls = getattr(mod, cls_name, None)
    if cls is None:
        msg = f"{cls_name!r} not found in {mod_name!r}"
        raise LookupError(msg)
    return cls


# Public re-export so tests can introspect the resolver without tripping
# pyright's reportPrivateUsage.
resolve_model = _resolve_model


def _cmd_schema_show(args: argparse.Namespace) -> int:
    cls = _resolve_model(args.model)
    from didactic.migrations._fingerprint import structural_fingerprint  # noqa: PLC0415
    from didactic.theory._theory import build_theory_spec  # noqa: PLC0415

    spec = build_theory_spec(cls)
    fp = structural_fingerprint(spec)
    schema = cls.model_json_schema()  # type: ignore[attr-defined]
    print(f"# Theory: {cls.__name__}")
    print(f"# fingerprint: {fp}")
    print()
    print("# spec:")
    print(json.dumps(spec, indent=2, sort_keys=True))
    print()
    print("# json_schema:")
    print(json.dumps(schema, indent=2, sort_keys=True))
    return 0


def _cmd_registry_list(_args: argparse.Namespace) -> int:
    from didactic.migrations._migrations import registered_fingerprints  # noqa: PLC0415

    pairs = registered_fingerprints()
    if not pairs:
        print("(empty registry)")
        return 0
    for src, tgt in pairs:
        print(f"{src[:12]}... -> {tgt[:12]}...")
    return 0


def _cmd_emit(args: argparse.Namespace) -> int:
    cls = _resolve_model(args.model)
    payload = cls.emit_as(args.target)  # type: ignore[attr-defined]
    if args.out == "-":
        sys.stdout.buffer.write(payload)
    else:
        from pathlib import Path  # noqa: PLC0415

        Path(args.out).write_bytes(payload)
        print(f"wrote {len(payload)} bytes to {args.out}")
    return 0


def _cmd_targets(_args: argparse.Namespace) -> int:
    from didactic.codegen import io as io_module  # noqa: PLC0415
    from didactic.codegen import list_emitters  # noqa: PLC0415
    from didactic.codegen import source as source_module  # noqa: PLC0415

    print("# custom emitters:")
    for name in list_emitters():
        print(f"  {name}")
    print()
    print("# IoRegistry protocols:")
    for name in io_module.list_protocols():
        print(f"  {name}")
    print()
    print("# AstParserRegistry grammars:")
    for name in source_module.available_targets():
        print(f"  {name}")
    return 0


def _cmd_check_breaking(args: argparse.Namespace) -> int:
    old = _resolve_model(args.old)
    new = _resolve_model(args.new)
    from didactic.migrations._diff import classify_change  # noqa: PLC0415

    report = classify_change(old, new)
    if report["compatible"]:
        print(f"compatible: {args.old} -> {args.new}")
        return 0
    print(f"BREAKING: {args.old} -> {args.new}")
    breaking = report.get("breaking")
    if isinstance(breaking, list):
        for change in breaking:
            print(f"  {change}")
    return 2


def _cmd_version(_args: argparse.Namespace) -> int:
    import panproto  # noqa: PLC0415

    from didactic.api import __version__  # noqa: PLC0415

    print(f"didactic {__version__}")
    print(f"panproto {getattr(panproto, '__version__', '<unknown>')}")
    return 0


def _dispatch_schema(args: argparse.Namespace) -> int:
    if args.schema_action == "show":
        return _cmd_schema_show(args)
    print("usage: didactic schema show <module:Class>", file=sys.stderr)
    return 1


def _dispatch_registry(args: argparse.Namespace) -> int:
    if args.registry_action == "list":
        return _cmd_registry_list(args)
    print("usage: didactic registry list", file=sys.stderr)
    return 1


def _dispatch_check(args: argparse.Namespace) -> int:
    if args.check_action == "breaking":
        return _cmd_check_breaking(args)
    print("usage: didactic check breaking <old> <new>", file=sys.stderr)
    return 1


_SUBCOMMANDS = {
    "schema": _dispatch_schema,
    "registry": _dispatch_registry,
    "emit": _cmd_emit,
    "targets": _cmd_targets,
    "check": _dispatch_check,
    "version": _cmd_version,
}

__all__ = [
    "main",
]
