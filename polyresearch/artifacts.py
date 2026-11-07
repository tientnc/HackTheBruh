"""Byte-level provenance for derived analysis artifacts."""

import hashlib
import json
from pathlib import Path

from .dataset import dump


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest(out, sources):
    files = {p.relative_to(out).as_posix(): sha256(p) for p in sorted(out.rglob("*"))
             if p.is_file() and p.name not in ("manifest.json", "README.md") and p.suffix != ".svg"}
    def source_name(path):
        path = Path(path).resolve()
        return path.relative_to(Path.cwd()).as_posix() if path.is_relative_to(Path.cwd()) else path.as_posix()
    value = {"algorithm": "sha256", "sources": {source_name(p): sha256(p) for p in sources},
             "files": files}
    dump(out / "manifest.json", value)
    return value


def verify(out):
    value = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    errors = [name for name, digest in value["files"].items()
              if not (out / name).is_file() or sha256(out / name) != digest]
    errors += [name for name, digest in value["sources"].items()
               if not Path(name).is_file() or sha256(name) != digest]
    if errors:
        raise ValueError(f"Changed or missing artifact/source files: {errors}")
    return len(value["files"])
