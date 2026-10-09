"""Filesystem-backed VCS for panproto schemas, plus Backref resolution."""

from didactic.vcs._backref import ModelPool, resolve_backrefs
from didactic.vcs._repo import Blame, CommittedDataset, Repository

__all__ = [
    "Blame",
    "CommittedDataset",
    "ModelPool",
    "Repository",
    "resolve_backrefs",
]
