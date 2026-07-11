#!/usr/bin/env python3

import os
from pathlib import Path
from typing import NamedTuple


class PathOwner(NamedTuple):
    path: Path
    uid: int
    gid: int


class OwnershipChange(NamedTuple):
    owner: PathOwner
    changed: bool
    skipped_reason: str | None = None


def is_effective_root():
    return hasattr(os, "geteuid") and os.geteuid() == 0


def nearest_existing_parent(path):
    path = Path(path)
    while not path.exists():
        parent = path.parent
        if parent == path:
            break
        path = parent
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def path_owner(path):
    path = nearest_existing_parent(path)
    stat_result = path.stat()
    return PathOwner(path=path, uid=stat_result.st_uid, gid=stat_result.st_gid)


def chown_tree(path, uid, gid, root=None):
    path = Path(path)
    paths = []
    if root is None:
        paths.append(path)
    else:
        root = Path(root)
        if path != root and not path.is_relative_to(root):
            raise ValueError(f"{path} is outside {root}")
        while True:
            paths.append(path)
            if path == root:
                break
            path = path.parent

    changed = 0
    for path in reversed(paths):
        if path.exists():
            os.chown(path, uid, gid, follow_symlinks=False)
            changed += 1

    target = paths[0]
    if target.is_dir():
        for path in target.rglob("*"):
            os.chown(path, uid, gid, follow_symlinks=False)
            changed += 1

    return changed


def chown_tree_to_existing_parent_owner(path, *, owner_source=None, root=None, skip_root_owner=True):
    owner = path_owner(owner_source or path)
    if skip_root_owner and owner.uid == 0 and owner.gid == 0:
        return OwnershipChange(owner=owner, changed=False, skipped_reason="owner source is root-owned")

    changed = chown_tree(path, owner.uid, owner.gid, root=root)
    return OwnershipChange(owner=owner, changed=bool(changed))
