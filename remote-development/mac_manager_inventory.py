#!/usr/bin/env python3
"""Inventory fixed Manager bundle resources without opening user data."""

import hashlib
from pathlib import Path


RESOURCE_NAMES = ("launch_manager.py", "RapBrainManagerNative.swift",
                  "dashboard_beta14.html", "manager_update_helper.py")
MAX_RESOURCE = 2_000_000


def resource_sha(path):
    if path.is_symlink() or not path.is_file():
        return None
    if path.stat().st_size > MAX_RESOURCE:
        raise ValueError("Ressource Manager trop volumineuse")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle(root, home):
    if any(parent.is_symlink() for parent in (root, *list(root.parents)[:-1])
           if parent != home and home in parent.parents):
        raise ValueError("Chemin Manager redirigé")
    if root.is_symlink() or not root.is_dir():
        return {"present": False}
    resources = root / "Contents" / "Resources"
    if (root.joinpath("Contents").is_symlink() or resources.is_symlink() or
            not resources.is_dir()):
        return {"present": True, "resources_valid": False}
    return {"present": True, "resources_valid": True,
            "sha256": {name: resource_sha(resources / name) for name in RESOURCE_NAMES}}


def inspect(home=None):
    home = Path.home() if home is None else Path(home)
    if home.is_symlink() or not home.is_dir():
        raise ValueError("Dossier utilisateur invalide")
    backup = home / "Downloads" / "RapBrainManagerBackups" / "secure-update"
    if any(path.is_symlink() for path in (home / "Downloads", backup.parent, backup)):
        raise ValueError("Chemin de sauvegarde redirigé")
    return {"schema": "rapbrain-manager-inventory-v1",
            "applications_bundle": bundle(home / "Applications" / "Rap Brain Manager.app", home),
            "beta14_bundle": bundle(home / "Downloads" / "RapBrainManager_App_Beta14" /
                                     "Rap Brain Manager Beta 14.app", home),
            "backup_state_present": backup.is_dir()}
