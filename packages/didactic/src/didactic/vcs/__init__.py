"""Filesystem-backed VCS for panproto schemas, plus Backref resolution."""

from didactic.vcs._backref import ModelPool, resolve_backrefs
from didactic.vcs._repo import (
    Blame,
    CommittedDataset,
    DecodedCommittedDataset,
    Repository,
)

__all__ = [
    "Blame",
    "CommittedDataset",
    "DecodedCommittedDataset",
    "ModelPool",
    "Repository",
    "resolve_backrefs",
]
