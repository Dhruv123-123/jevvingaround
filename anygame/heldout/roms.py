"""Where a game's ROM comes from. A freely licensed game names a URL and a sha256: it is fetched once into the cache
and checked. A commercial game names a local path (and optionally an environment variable): it is never fetched, and
a run without it skips the game and says so. Nothing is written into the repository.

The cache is ANYGAME_HELDOUT_ROMS, else /mnt/project-files/roms/heldout when that folder's parent exists, else
~/.cache/anygame/heldout."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
from typing import Any


class NoRom(Exception):
    pass


def cache_dir() -> Path:
    if os.environ.get("ANYGAME_HELDOUT_ROMS"):
        return Path(os.environ["ANYGAME_HELDOUT_ROMS"])
    if Path("/mnt/project-files/roms").is_dir():
        return Path("/mnt/project-files/roms/heldout")
    return Path.home() / ".cache" / "anygame" / "heldout"


def _digest(p: Path, algo: str) -> str:
    return hashlib.new(algo, p.read_bytes()).hexdigest()


def _verify(p: Path, rom: dict[str, Any]) -> None:
    for algo in ("sha256", "sha1"):
        if rom.get(algo) and _digest(p, algo) != rom[algo].lower():
            raise NoRom(f"{p}: {algo} does not match the game file (a different dump or version)")


def resolve(game: dict[str, Any], fetch: bool = True) -> Path:
    rom = game["rom"]
    if "url" in rom:
        dest = cache_dir() / f"{game['id']}{Path(rom['url']).suffix}"
        if not dest.exists():
            if not fetch:
                raise NoRom(f"{game['id']}: not in {dest.parent} (run with fetching on)")
            import requests
            r = requests.get(rom["url"], timeout=60)
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(r.content)
            _verify(tmp, rom)
            tmp.replace(dest)
        _verify(dest, rom)
        return dest
    p = Path(os.environ.get(rom.get("env", ""), "") or rom["path"])
    if not p.exists():
        roms = Path(rom["path"]).parent
        alt = sorted(roms.glob("*.gb")) if roms.is_dir() else []
        raise NoRom(f"{game['id']}: no ROM at {p}" + (f" (found {', '.join(a.name for a in alt)}; set {rom.get('env')} to use one)" if alt else ""))
    _verify(p, rom)
    return p
