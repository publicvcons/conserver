"""Shared base for PublicVCons vcon-server links.

These link modules are written to the upstream vcon-server contract:

    default_options = {...}
    def run(vcon_uuid, link_name, opts=default_options) -> str | None

When running inside a deployed vcon-server, the vCon lives in Redis and
is reached via ``lib.vcon_redis.VconRedis``. On the offline Mac mini we
do not run Redis (PROTOTYPE_PLAN.md §8 keeps the mini closed), so the
same link code must also work against a filesystem-backed store. This
module resolves whichever is available; the link body is identical
either way (`store.get_vcon(uuid)` / `store.store_vcon(vcon)`).

This is a compatibility shim for running one body of code in two
environments, not a reimplementation of vcon-server.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logging.basicConfig(
    level=os.environ.get("PVCONS_LOG", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def init_logger(name: str) -> logging.Logger:
    try:  # prefer vcon-server's logger when embedded
        from lib.logging_utils import init_logger as _il  # type: ignore
        return _il(name)
    except Exception:
        return logging.getLogger(name)


class FileVconStore:
    """Filesystem stand-in for vcon-server's VconRedis.

    vCons are stored as ``<root>/<uuid>.vcon.json`` using the upstream
    ``vcon`` library object, so links manipulate a real Vcon exactly as
    they would in the server.
    """

    def __init__(self, root: str | None = None):
        self.root = Path(root or os.environ.get(
            "PVCONS_VCON_STORE",
            "/Volumes/publicvcons/work/_vcon_store"))
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, uuid: str) -> Path:
        return self.root / f"{uuid}.vcon.json"

    def get_vcon(self, uuid: str):
        from vcon import Vcon
        return Vcon.load_from_file(str(self._path(uuid)))

    def store_vcon(self, vcon) -> None:
        self._path(vcon.uuid).write_text(vcon.to_json())


def get_store():
    """Return a vCon store: vcon-server's VconRedis if embedded, else file."""
    if os.environ.get("PVCONS_FORCE_FILE_STORE") != "1":
        try:
            from lib.vcon_redis import VconRedis  # type: ignore
            return VconRedis()
        except Exception:
            pass
    return FileVconStore()


def pvcons_env() -> dict:
    """Parse ~/.publicvcons.env (`export K=V` lines) into a dict.

    launchd / nohup runs do not source the shell rc, so the pyannote
    subprocess would otherwise lack HUGGING_FACE_HUB_TOKEN / HF_HOME.
    """
    env = {}
    f = Path(os.environ.get("PVCONS_ENV_FILE",
                            Path.home()/".publicvcons.env"))
    if not f.is_file():
        return env
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_source_profile(source_id: str) -> dict:
    """Read a source profile YAML by id from the sibling sources/ dir."""
    import yaml
    sources = Path(__file__).resolve().parents[1] / "sources"
    fp = sources / f"{source_id}.yaml"
    if not fp.is_file():
        raise FileNotFoundError(f"no source profile: {fp}")
    return yaml.safe_load(fp.read_text())
