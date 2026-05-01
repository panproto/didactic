# Wraps panproto's ``Repository`` whose method signatures
# (``log() -> list[dict[str, object]]``, ``resolve_ref() -> str | None``,
# ``add(target: Schema)``) don't line up exactly with didactic's
# narrower public surface. The runtime contract is honoured; the
# stub-side narrowing is deferred. Tracked in panproto/didactic#1.
# pyright: reportReturnType=false, reportArgumentType=false
"""Filesystem-backed VCS for panproto schemas.

Wraps ``panproto.Repository`` with a didactic-shaped public surface.
The wrapper exists so that the public ``didactic`` namespace owns the
API contract: panproto's Repository is the storage implementation, but
downstream code never imports it directly. This mirrors the same
posture didactic takes elsewhere (Theory specs, fingerprints, lenses):
didactic owns the public shape, panproto is the runtime.

Surface
-------
The wrapper covers initialisation, staging (either a panproto
``Schema`` or a [Model][didactic.api.Model] subclass), committing, the
read-only introspection accessors (``head``, ``log``, ``working_dir``,
branch listing), and ref / branch operations. Staging a Model class
synthesises a single-vertex schema via
``panproto.Protocol.from_theories`` over the Model's Theory.

Notes
-----
Each [Repository][didactic.api.Repository] holds an open handle to the
underlying ``.panproto/`` directory. Two ``Repository`` instances over
the same path are independent handles to the same on-disk store.

See Also
--------
didactic.theory._theory : the Model-to-Theory bridge.
panproto.Repository : the wrapped runtime type.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from os import PathLike

    import panproto

    from didactic.models._model import Model
    from didactic.types._typing import JsonObject


class Repository:
    """Filesystem-backed panproto repository.

    Wraps a ``panproto.Repository``. Construction is
    via the [Repository.init][didactic.api.Repository.init] and
    [Repository.open][didactic.api.Repository.open] class methods rather
    than the bare constructor; the constructor accepts an already-open
    handle and is mostly for internal use.

    Parameters
    ----------
    inner
        An already-constructed ``panproto.Repository``. Most callers
        should use [init][didactic.api.Repository.init] or
        [open][didactic.api.Repository.open] instead of constructing this
        class directly.

    Notes
    -----
    The wrapper delegates almost every operation to the inner panproto
    handle. The reason it exists, rather than re-exporting panproto's
    type, is to keep didactic's public API independent of panproto's
    Python binding details (attribute names, argument keywords, etc.)
    as panproto evolves.

    Examples
    --------
    >>> import didactic.api as dx
    >>> repo = dx.Repository.init("/tmp/my-repo")  # doctest: +SKIP
    >>> repo.head() is None  # doctest: +SKIP
    True
    """

    __slots__ = ("_inner",)

    def __init__(self, inner: panproto.Repository) -> None:
        self._inner = inner

    # construction --------------------------------------------------

    @classmethod
    def init(cls, path: str | PathLike[str]) -> Repository:
        """Initialise a new repository at ``path``.

        Parameters
        ----------
        path
            Directory in which to create the ``.panproto/`` store. The
            directory is created if it does not exist.

        Returns
        -------
        Repository
            A handle to the newly initialised repository.

        Raises
        ------
        panproto.VcsError
            If a repository already exists at ``path`` or the path is
            not writable.
        """
        import panproto  # noqa: PLC0415

        return cls(panproto.Repository.init(str(path)))

    @classmethod
    def open(cls, path: str | PathLike[str]) -> Repository:
        """Open an existing repository at ``path``.

        Parameters
        ----------
        path
            Directory containing a ``.panproto/`` store.

        Returns
        -------
        Repository
            A handle to the existing repository.

        Raises
        ------
        panproto.VcsError
            If no repository exists at ``path``.
        """
        import panproto  # noqa: PLC0415

        return cls(panproto.Repository.open(str(path)))

    # introspection -------------------------------------------------

    @property
    def working_dir(self) -> str:
        """Path to the repository's working directory."""
        return self._inner.working_dir

    def head(self) -> str | None:
        """Resolve ``HEAD`` to a commit object id.

        Returns
        -------
        str or None
            The commit id, or ``None`` if the repository has no
            commits yet.
        """
        return self._inner.head()

    def head_state(self) -> str:
        """Describe the current HEAD state.

        Returns
        -------
        str
            A descriptor string from panproto. For a freshly
            initialised repository this is typically
            ``"ref: refs/heads/main"``.
        """
        return self._inner.head_state()

    def has_staged(self) -> bool:
        """Return ``True`` if anything is staged for the next commit."""
        return self._inner.has_staged()

    def list_branches(self) -> list[tuple[str, str]]:
        """Return the list of branches.

        Returns
        -------
        list of (str, str)
            One ``(name, commit_id)`` tuple per branch.
        """
        return list(self._inner.list_branches())

    def list_tags(self) -> list[tuple[str, str]]:
        """Return the list of tags.

        Returns
        -------
        list of (str, str)
            One ``(name, target_id)`` tuple per tag.
        """
        return list(self._inner.list_tags())

    def log(self) -> list[JsonObject]:
        """List commits reachable from HEAD, newest first.

        Returns
        -------
        list of dict
            One commit-record dict per commit, in newest-first order.
            The exact shape is panproto-defined; callers that depend
            on specific keys should consult panproto's documentation.
        """
        return list(self._inner.log())

    def resolve_ref(self, ref: str) -> str:
        """Resolve a ref expression to a commit id.

        Parameters
        ----------
        ref
            A branch name, tag name, or commit-id prefix.

        Returns
        -------
        str
            The full commit id.

        Raises
        ------
        panproto.VcsError
            If ``ref`` does not resolve to a commit.
        """
        return self._inner.resolve_ref(ref)

    # mutation ------------------------------------------------------

    def add(self, target: panproto.Schema | type) -> None:
        """Stage ``target`` for the next commit.

        Parameters
        ----------
        target
            Either a ``panproto.Schema`` or a [Model][didactic.api.Model]
            subclass. When given a Model class, didactic builds a
            schema using ``panproto.Protocol.from_theories`` over the
            Model's Theory.

        Notes
        -----
        Staging is additive: subsequent calls accumulate in the index
        until a [commit][didactic.api.Repository.commit] flushes it.
        """
        from didactic.models._model import Model  # noqa: PLC0415

        if isinstance(target, type) and issubclass(target, Model):
            self._inner.add(schema_from_model(target))
            return
        self._inner.add(target)

    def commit(
        self,
        message: str,
        *,
        author: str,
        skip_verify: bool = False,
    ) -> str:
        """Create a commit with ``message`` and ``author``.

        Parameters
        ----------
        message
            The commit message.
        author
            The commit author. Free-form string; the conventional
            shape is ``"Name <email>"``.
        skip_verify
            If ``True``, skip the panproto-side verification step.
            Defaults to ``False``.

        Returns
        -------
        str
            The new commit's object id.

        Raises
        ------
        panproto.VcsError
            If nothing is staged or panproto rejects the commit.
        """
        return self._inner.commit(message, author, skip_verify=skip_verify)

    def create_branch(self, name: str, commit_id: str) -> None:
        """Create a new branch ``name`` pointing at ``commit_id``."""
        self._inner.create_branch(name, commit_id)

    def checkout_branch(self, name: str) -> None:
        """Switch HEAD to branch ``name``."""
        self._inner.checkout_branch(name)

    # representation ------------------------------------------------

    def __repr__(self) -> str:
        return f"Repository(at={self._inner.working_dir!r})"


def schema_from_model(cls: type[Model]) -> panproto.Schema:
    """Build a single-vertex panproto Schema from a Model class.

    Parameters
    ----------
    cls
        A [Model][didactic.api.Model] subclass.

    Returns
    -------
    panproto.Schema
        A schema with the Model's Theory acting as both the
        schema-theory and the instance-theory of a synthesised
        ``Protocol``, plus one vertex named after the class with
        kind ``"object"``.
    """
    import panproto  # noqa: PLC0415

    from didactic.theory._theory import build_theory  # noqa: PLC0415

    theory = build_theory(cls)
    protocol = panproto.Protocol.from_theories(
        name=cls.__name__,
        schema_theory=theory,
        obj_kinds=["object"],
    )
    builder = protocol.schema()
    builder.vertex(cls.__name__, "object")
    return builder.build()


__all__ = [
    "Repository",
]
