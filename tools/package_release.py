"""Build ChainsOfTheAbyssalChoir_Pygame_R2.zip from a CLEAN tree and verify it.

The archive is made from ``git archive HEAD`` when the project is a git checkout (so uncommitted files, caches,
saves and scratch never leak in), otherwise from a walk of the tree with the same exclusions. It is then extracted to a
temp dir where compileall, validate_content, smoke_test and the unittest suite are run.
Usage: python tools/package_release.py [output_dir]
"""
from __future__ import annotations

import hashlib
import io
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT.parent
TOP = "ChainsOfTheAbyssalChoir_Pygame"
ZIP_PATH = OUT_DIR / "ChainsOfTheAbyssalChoir_Pygame_R2.zip"
EXCLUDE_DIRS = {".git", "__pycache__", ".pytest_cache", "saves", "preview_out"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".bak"}
EXCLUDE_NAMES = {"gitignore.txt", ".gitignore", "update_test_report.py"}


def _keep(rel: pathlib.PurePosixPath) -> bool:
    return not (set(rel.parts[:-1]) & EXCLUDE_DIRS or rel.suffix in EXCLUDE_SUFFIX or rel.name in EXCLUDE_NAMES)


def _files() -> list[tuple[pathlib.PurePosixPath, bytes]]:
    out: list[tuple[pathlib.PurePosixPath, bytes]] = []
    if (ROOT / ".git").exists():
        status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        if status:
            print("WARNING: uncommitted changes are NOT included (building from HEAD):\n" + status)
        raw = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, capture_output=True, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
            for m in tf.getmembers():
                if m.isfile() and _keep(pathlib.PurePosixPath(m.name)):
                    out.append((pathlib.PurePosixPath(m.name), tf.extractfile(m).read()))  # type: ignore[union-attr]
    else:
        for p in sorted(ROOT.rglob("*")):
            rel = pathlib.PurePosixPath(p.relative_to(ROOT).as_posix())
            if p.is_file() and _keep(rel):
                out.append((rel, p.read_bytes()))
    return out


def build() -> int:
    files = _files()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for rel, data in files:
            zf.writestr(f"{TOP}/{rel.as_posix()}", data)
    digest = hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest()
    (OUT_DIR / "SHA256SUMS_R2.txt").write_text(f"{digest}  {ZIP_PATH.name}\n")
    print(f"Wrote {ZIP_PATH} ({ZIP_PATH.stat().st_size / 1_048_576:.1f} MB, {len(files)} files)\nSHA-256 {digest}")
    return len(files)


def verify() -> bool:
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(ZIP_PATH) as zf:
            bad = [n for n in zf.namelist() if any(p in EXCLUDE_DIRS for p in n.split("/")[:-1]) or n.endswith((".pyc", ".bak"))]
            if bad:
                print("FAIL: junk in archive:", bad[:5])
                return False
            zf.extractall(td)
        root = pathlib.Path(td) / TOP
        env = {**os.environ, "SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy", "PYTHONDONTWRITEBYTECODE": "1"}
        ok_all = True
        for need in ("main.py", "requirements.txt", "README.md", "TEST_REPORT.md", "CHANGELOG_R2.md", "DESIGN_NOTES.md",
                     "CONTRIBUTING.md", "ASSET_MANIFEST_R2.md", "Assets/Art/models/fallen_angel.png"):
            if not (root / need).is_file():
                print("FAIL: missing", need)
                ok_all = False
        for cmd in ([sys.executable, "-m", "compileall", "-q", "."], [sys.executable, "tools/validate_content.py"],
                    [sys.executable, "tools/smoke_test.py"], [sys.executable, "-m", "unittest", "discover", "-s", "tests"]):
            r = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True)
            tail = (r.stderr.strip().splitlines() or r.stdout.strip().splitlines() or [""])[-1]
            print(f"  exit {r.returncode}: {' '.join(cmd[1:])}  [{tail[:90]}]")
            # unittest is expected to report exactly the 2 documented real-pygame errors without pygame-ce installed
            if "unittest" in cmd:
                ok_all &= "errors=2" in tail and "failures" not in tail
            else:
                ok_all &= r.returncode == 0
        print("Extracted-archive verification:", "PASSED (with the 2 documented real-pygame errors)" if ok_all else "FAILED")
        return ok_all


if __name__ == "__main__":
    build()
    sys.exit(0 if verify() else 1)
