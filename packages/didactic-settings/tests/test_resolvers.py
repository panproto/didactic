"""The built-in resolvers, the registry and ``lookup``."""

from __future__ import annotations

import pytest

from didactic.settings import (
    InterpolationError,
    list_resolvers,
    lookup,
    register_resolver,
    resolve,
    unregister_resolver,
)
from didactic.settings._resolvers import register_builtins

ROOT = {
    "paths": {"data_dir": "/d", "out": None},
    "trainer": {"epochs": 3, "tags": ["a", "b"]},
    "loop": "${bad.self:x}",
    "text": "7",
}


def test_builtins_are_registered() -> None:
    names = list_resolvers()
    assert names == tuple(sorted(names))
    for name in (
        "oc.env",
        "oc.select",
        "oc.decode",
        "oc.deprecated",
        "oc.create",
        "oc.dict.keys",
        "oc.dict.values",
    ):
        assert name in names


# -- oc.select ----------------------------------------------------------------


def test_oc_select_present_missing_null_and_default() -> None:
    assert resolve("${oc.select:trainer.epochs}", root=ROOT) == 3
    assert resolve("${oc.select:trainer.missing}", root=ROOT) is None
    assert resolve("${oc.select:paths.out}", root=ROOT) is None
    assert resolve("${oc.select:trainer.missing,7}", root=ROOT) == 7
    assert resolve("${oc.select:paths.out,x}", root=ROOT) == "x"
    assert resolve("${oc.select:paths.out,[1,2]}", root=ROOT) == [1, 2]
    assert resolve("${oc.select:trainer.tags[1]}", root=ROOT) == "b"
    assert resolve("${oc.select:trainer.tags[5],z}", root=ROOT) == "z"


def test_oc_select_without_arguments() -> None:
    with pytest.raises(InterpolationError, match="requires a path"):
        resolve("${oc.select:}", root=ROOT)


# -- oc.dict.* ----------------------------------------------------------------


def test_oc_dict_keys_and_values() -> None:
    assert resolve("${oc.dict.keys:paths}", root=ROOT) == ["data_dir", "out"]
    assert resolve("${oc.dict.values:paths}", root=ROOT) == ["/d", None]
    assert resolve("${oc.dict.keys:trainer}", root=ROOT) == ["epochs", "tags"]


def test_oc_dict_non_mapping_and_missing() -> None:
    with pytest.raises(InterpolationError) as info:
        resolve("${oc.dict.keys:text}", root=ROOT)
    assert str(info.value) == "oc.dict.keys: 'text' is not a mapping"
    with pytest.raises(InterpolationError) as values:
        resolve("${oc.dict.values:trainer.tags}", root=ROOT)
    assert "oc.dict.values: 'trainer.tags' is not a mapping" in str(values.value)
    with pytest.raises(InterpolationError, match="unresolved"):
        resolve("${oc.dict.keys:nowhere}", root=ROOT)
    with pytest.raises(InterpolationError, match="requires a path"):
        resolve("${oc.dict.keys:}", root=ROOT)


# -- oc.deprecated -------------------------------------------------------------


def test_oc_deprecated_warns_and_reads_the_new_path() -> None:
    with pytest.warns(
        DeprecationWarning,
        match=r"'<root>' is deprecated\. Change your code and config to use "
        r"'trainer\.epochs'",
    ):
        assert resolve("${oc.deprecated:trainer.epochs}", root=ROOT) == 3


def test_oc_deprecated_substitutes_old_and_new_keys_in_a_custom_message() -> None:
    document = {
        "old": "${oc.deprecated:new,use $NEW_KEY instead of $OLD_KEY}",
        "new": 5,
    }
    with pytest.warns(DeprecationWarning, match="use new instead of old"):
        assert resolve(document, root=document) == {"old": 5, "new": 5}


def test_oc_deprecated_without_a_path() -> None:
    with pytest.raises(InterpolationError, match="requires a replacement path"):
        resolve("${oc.deprecated:}", root=ROOT)


# -- oc.create -------------------------------------------------------------------


def test_oc_create_reads_the_scalar_grammar() -> None:
    assert resolve("${oc.create:[1, 2]}", root=ROOT) == [1, 2]
    assert resolve('${oc.create:{"a": true}}', root=ROOT) == {"a": True}
    assert resolve("${oc.create:3}", root=ROOT) == 3
    assert resolve("${oc.create:null}", root=ROOT) is None
    assert resolve("${oc.create:word}", root=ROOT) == "word"
    assert resolve("${oc.create:${trainer.epochs}}", root=ROOT) == 3


# -- oc.env and oc.decode ---------------------------------------------------------


def test_oc_env_default_joins_the_remaining_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DIDACTIC_TEST_VAR", raising=False)
    assert resolve("${oc.env:DIDACTIC_TEST_VAR,a,b}", root=ROOT) == "a,b"
    monkeypatch.setenv("DIDACTIC_TEST_VAR", "set")
    assert resolve("${oc.env:DIDACTIC_TEST_VAR,a,b}", root=ROOT) == "set"
    with pytest.raises(InterpolationError, match="requires at least one argument"):
        resolve("${oc.env:}", root=ROOT)


def test_oc_decode_refuses_bad_base64_and_unknown_encodings() -> None:
    with pytest.raises(InterpolationError) as info:
        resolve("${oc.decode:not base64}", root=ROOT)
    assert str(info.value).startswith(
        "oc.decode: 'not base64' is not base64-encoded UTF-8 text: "
    )
    assert resolve("${oc.decode:aGk=}", root=ROOT) == "hi"
    with pytest.raises(InterpolationError, match="unknown encoding"):
        resolve("${oc.decode:aGk=,latin-1}", root=ROOT)
    assert resolve("${oc.decode:plain,utf-8}", root=ROOT) == "plain"
    with pytest.raises(InterpolationError, match="requires at least a value"):
        resolve("${oc.decode:}", root=ROOT)


# -- lookup ----------------------------------------------------------------------


def test_lookup_outside_an_active_resolve_is_refused() -> None:
    with pytest.raises(InterpolationError) as info:
        lookup("paths.data_dir")
    assert str(info.value) == "lookup() called outside an active resolve()"
    assert info.value.path is None


def test_lookup_refuses_an_empty_path() -> None:
    def empty(*_: str) -> str:
        return str(lookup(""))

    with pytest.raises(InterpolationError) as info:
        resolve("${e:}", root=ROOT, resolvers={"e": empty})
    assert str(info.value) == "lookup() expects a dotted path; got ''"


def test_lookup_reads_the_active_tree_and_indexes_lists() -> None:
    def joined(*args: str) -> str:
        return f"{lookup('paths.data_dir')}/{lookup('trainer.tags.1')}/{','.join(args)}"

    assert resolve(
        "${custom.join:x,y}", root=ROOT, resolvers={"custom.join": joined}
    ) == ("/d/b/x,y")


def test_lookup_refuses_a_non_path_argument() -> None:
    def bad(*_: str) -> str:
        return str(lookup("oc.env:HOME"))

    with pytest.raises(InterpolationError, match="lookup\\(\\) expects a dotted path"):
        resolve("${bad:}", root=ROOT, resolvers={"bad": bad})


def test_cycle_through_a_resolver_is_reported_as_a_cycle() -> None:
    def self_path(*_: str) -> str:
        return str(lookup("loop"))

    with pytest.raises(InterpolationError, match="cycle") as info:
        resolve(
            ROOT["loop"], root=ROOT, here=("loop",), resolvers={"bad.self": self_path}
        )
    assert info.value.path == ("loop",)


def test_lookup_unresolved_path_raises_the_engine_error() -> None:
    def missing(*_: str) -> str:
        return str(lookup("paths.nowhere"))

    with pytest.raises(InterpolationError, match="Reference paths.nowhere unresolved"):
        resolve("${m:}", root=ROOT, resolvers={"m": missing})


# -- registry ----------------------------------------------------------------------


def test_per_call_resolvers_shadow_the_registry_for_that_call_only() -> None:
    assert resolve(
        "${oc.create:1}", root=ROOT, resolvers={"oc.create": lambda *_: "x"}
    ) == ("x")
    assert resolve("${oc.create:1}", root=ROOT) == 1


def test_register_replace_unregister() -> None:
    register_resolver("test.upper", lambda *a: ",".join(a).upper())
    try:
        with pytest.raises(ValueError, match="already registered"):
            register_resolver("test.upper", lambda *a: "")
        assert resolve("${test.upper:a,b}", root=ROOT) == "A,B"
        register_resolver("test.upper", lambda *a: "replaced", replace=True)
        assert resolve("${test.upper:a}", root=ROOT) == "replaced"
    finally:
        unregister_resolver("test.upper")
    unregister_resolver("test.upper")
    assert "test.upper" not in list_resolvers()
    with pytest.raises(InterpolationError, match="Unknown resolver 'test.upper'"):
        resolve("${test.upper:a}", root=ROOT)


def test_register_builtins_restores_an_unregistered_builtin() -> None:
    unregister_resolver("oc.create")
    assert "oc.create" not in list_resolvers()
    register_builtins()
    assert resolve("${oc.create:2}", root=ROOT) == 2


# -- argument splitting and exception wrapping -----------------------------------------


def test_arguments_split_outside_brackets_braces_and_quotes() -> None:
    received: list[tuple[str, ...]] = []

    def capture(*args: str) -> str:
        received.append(args)
        return "ok"

    resolvers = {"cap": capture}
    resolve("${cap:[1, 2],x}", root=ROOT, resolvers=resolvers)
    resolve('${cap:{"a": 1, "b": 2}}', root=ROOT, resolvers=resolvers)
    resolve('${cap:"x,y",z}', root=ROOT, resolvers=resolvers)
    resolve("${cap:'p,q'}", root=ROOT, resolvers=resolvers)
    resolve("${cap:${oc.select:paths.out,a},b}", root=ROOT, resolvers=resolvers)
    # a quoted argument is unquoted, as in OmegaConf
    assert received == [
        ("[1, 2]", "x"),
        ('{"a": 1, "b": 2}',),
        ("x,y", "z"),
        ("p,q",),
        ("a", "b"),
    ]


def test_resolver_exceptions_are_wrapped_with_the_leaf_path() -> None:
    def boom(*_: str) -> str:
        raise KeyError("nope")

    with pytest.raises(InterpolationError) as info:
        resolve({"k": "${boom:}"}, root=ROOT, resolvers={"boom": boom})
    assert (
        str(info.value) == "Resolver 'boom' raised KeyError: 'nope'; at config key 'k'"
    )
    assert info.value.path == ("k",)
    assert isinstance(info.value.__cause__, KeyError)


def test_interpolation_error_from_a_resolver_passes_through() -> None:
    def refuse(*_: str) -> str:
        raise InterpolationError("refused")

    with pytest.raises(InterpolationError, match="^refused$"):
        resolve("${r:}", root=ROOT, resolvers={"r": refuse})
