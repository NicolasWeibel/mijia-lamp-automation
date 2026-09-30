"""Repository-level checks that do not require Windows or a lamp."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_ROOT_PATHS = (
    ROOT / "config.json",
    ROOT / "mi-tokens.json",
    ROOT / "secrets",
    ROOT / "data",
    ROOT / "logs",
    ROOT / "prepared-runtime",
    ROOT / "wheelhouse",
)
REQUIRED_PUBLIC_FILES = (
    "LICENSE",
    "pyproject.toml",
    "config.example.json",
    "config.schema.json",
    "requirements.miio.lock.txt",
    "service.py",
    "agent.py",
    "portable.py",
    "setup-portable.ps1",
    "prepare-service-runtime.ps1",
    "security-check.ps1",
    "SECURITY.md",
    "CHANGELOG.md",
    "scripts/verify_release.py",
)
TOKEN_LIKE = re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])")
TEXT_SUFFIXES = {".py", ".ps1", ".cmd", ".json", ".md", ".toml", ".yml", ".yaml", ".txt"}
PROJECT_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
PACKAGE_VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
VERSIONED_SCRIPTS = {
    "install.ps1": r'^\$ProjectVersion\s*=\s*"([^"]+)"',
    "prepare-service-runtime.ps1": r'^\s*project_version\s*=\s*"([^"]+)"',
    "setup-portable.ps1": r'\$manifest\.project_version\s*-ne\s*"([^"]+)"',
    "scripts/build-dependency-manifest.ps1": r'\$manifest\.project_version\s*-ne\s*"([^"]+)"',
}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def _project_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = PROJECT_VERSION_RE.search(text)
    if not match:
        fail("pyproject.toml no contiene project.version legible")
    return match.group(1)


def _package_version() -> str:
    text = (ROOT / "mijialamp" / "__init__.py").read_text(encoding="utf-8")
    match = PACKAGE_VERSION_RE.search(text)
    if not match:
        fail("mijialamp/__init__.py no contiene __version__ legible")
    return match.group(1)


def check_hygiene() -> None:
    for path in FORBIDDEN_ROOT_PATHS:
        if path.exists():
            fail(f"private/runtime path must not be present in repository: {path.relative_to(ROOT)}")

    for name in REQUIRED_PUBLIC_FILES:
        if not (ROOT / name).is_file():
            fail(f"required public file is missing: {name}")

    project_version = _project_version()
    package_version = _package_version()
    if project_version != package_version:
        fail(f"version mismatch: pyproject={project_version}, package={package_version}")
    for name, pattern in VERSIONED_SCRIPTS.items():
        script = (ROOT / name).read_text(encoding="utf-8")
        match = re.search(pattern, script, re.MULTILINE)
        if not match or match.group(1) != project_version:
            fail(f"version mismatch in {name}: expected {project_version}")
    git_ref = os.environ.get("GITHUB_REF", "")
    if git_ref.startswith("refs/tags/") and git_ref.removeprefix("refs/tags/") != f"v{project_version}":
        fail(f"release tag {git_ref!r} does not match project version v{project_version}")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## [{project_version}]" not in changelog:
        fail(f"CHANGELOG.md no contiene una entrada para {project_version}")

    example = ROOT / "config.example.json"
    with example.open("r", encoding="utf-8") as fh:
        config = json.load(fh)
    if "token" in config:
        fail("config.example.json must not contain a token field")
    if config.get("$schema") != "./config.schema.json":
        fail("config.example.json must reference config.schema.json")
    if config.get("version") != 3:
        fail("config.example.json must use schema version 3")

    schema = json.loads((ROOT / "config.schema.json").read_text(encoding="utf-8"))
    if schema.get("properties", {}).get("version", {}).get("const") != 3:
        fail("config.schema.json must describe schema v3")
    if schema.get("additionalProperties") is not False:
        fail("config.schema.json must reject unknown top-level properties")

    # Keep example/schema mechanically aligned so editor validation and runtime validation
    # do not silently drift apart.
    schema_properties = set(schema.get("properties", {}))
    example_keys = set(config)
    missing_schema = sorted(example_keys - schema_properties)
    if missing_schema:
        fail("config.example.json keys missing from schema: " + ", ".join(missing_schema))

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for required in ("config.json", "secrets/", "data/", "logs/", "mi-tokens.json", "prepared-runtime/"):
        if required not in gitignore:
            fail(f".gitignore does not protect {required}")

    # Public source should never contain a raw miIO-shaped 32-hex secret. Git SHAs
    # are 40 hex chars and are deliberately unaffected by this check.
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in {".venv", ".git", "release", "__pycache__"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if TOKEN_LIKE.search(text):
            fail(f"possible raw 32-hex token in public source: {path.relative_to(ROOT)}")


def run_tests() -> None:
    command = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-p",
        "test_*.py",
        "-v",
    ]
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)


def main() -> int:
    check_hygiene()
    run_tests()
    print("Repository checks: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
