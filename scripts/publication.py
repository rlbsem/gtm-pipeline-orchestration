"""Explicit public-file allowlist, link checks, exact archive verification and content safety."""
import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = {"README.md", "LICENSE", "pyproject.toml", "requirements.txt", "requirements.lock", "Dockerfile",
       "compose.yml", ".gitignore", ".gitattributes", ".dockerignore"}
DIRS = {"src", "web", "tests", "scripts", "docs", ".github"}


def files():
    allowed = []
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT)
        if not p.is_file() or any(part in {"__pycache__", ".pytest_cache"} for part in rel.parts):
            continue
        if str(rel).replace("\\", "/") == "package-manifest.json":
            continue
        if rel.parts[0] in DIRS or rel.as_posix() in TOP:
            if p.suffix.lower() in {".sqlite", ".db", ".pem", ".key", ".pyc", ".log"} or p.is_symlink():
                raise ValueError("private_file_in_public_tree:" + rel.as_posix())
            allowed.append(p)
    return sorted(allowed)


def checks():
    for p in files():
        if p.suffix in {".png", ".jpg"}:
            continue
        text = p.read_text(encoding="utf-8")
        for pattern in [r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----", r"gh[pousr]_[A-Za-z0-9]{30,}",
                        r"AKIA[A-Z0-9]{16}", r"C:[/\\]Users[/\\]", r"Bearer [A-Za-z0-9_-]{25,}"]:
            if re.search(pattern, text):
                raise ValueError("sensitive_content:" + p.relative_to(ROOT).as_posix())
        if p.suffix == ".md":
            for target in re.findall(r"\]\(([^)]+)\)", text):
                if re.match(r"(?:https?://|mailto:|#)", target):
                    continue
                target = target.split("#")[0]
                if target and not (p.parent / target).resolve().is_file():
                    raise ValueError(f"broken_link:{p.relative_to(ROOT)}:{target}")
    return {"public_content_scan": "passed", "local_markdown_links": "passed"}


def source_hashes():
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files() if p.relative_to(ROOT).parts[0] in {"src", "web", "tests", "scripts", ".github"}}


def manifest(write=False):
    expected = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files()}
    path = ROOT / "package-manifest.json"
    if write:
        path.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif json.loads(path.read_text()) != expected:
        raise ValueError("package_manifest_mismatch")
    return expected


def package():
    checks()
    hashes = manifest()
    output = ROOT / "dist/GTM_Pipeline_Orchestration_Review.zip"
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel in [*hashes, "package-manifest.json"]:
            archive.write(ROOT / rel, "gtm-pipeline-orchestration/" + rel)
    with zipfile.ZipFile(output) as archive:
        assert len(archive.namelist()) == len(hashes) + 1
        for rel, expected in hashes.items():
            assert hashlib.sha256(archive.read("gtm-pipeline-orchestration/" + rel)).hexdigest() == expected
    return {"files_verified": len(hashes), "zip": output.name,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--package", action="store_true")
    args = parser.parse_args()
    print(json.dumps(checks()))
    manifest(write=args.refresh)
    if args.package:
        print(json.dumps(package()))
