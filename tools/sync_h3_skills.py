#!/usr/bin/env python3
"""Sync the bundled official MiniMax-H3 skill library from GitHub.

Stdlib-only so it runs anywhere (ComfyUI machine cron, GitHub Actions, manual).
Source of truth: https://github.com/MiniMax-AI/MiniMax-H3  (path: skills/)

Usage:
    python tools/sync_h3_skills.py --dry-run     # show what would change
    python tools/sync_h3_skills.py               # apply (backs up first)

Exit codes: 0 = already up to date, 10 = changes applied, 2 = error.
New/removed skills need a ComfyUI restart (registry is built at import);
editing existing SKILL.md bodies takes effect on the next run.
"""

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from datetime import datetime, timezone

DEFAULT_REPO = "MiniMax-AI/MiniMax-H3"
DEFAULT_REF = "main"
UPSTREAM_PREFIX = "skills/"
API = "https://api.github.com"
CODELOAD = "https://codeload.github.com"
DEST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "h3_skills")
SYNC_META = ".sync_source.json"


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": "comfyui-alex-node-minimax-local/sync_h3_skills",
        "Accept": "application/vnd.github+json",
    })
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def resolve_commit(repo: str, ref: str) -> str:
    payload = json.loads(_fetch(f"{API}/repos/{repo}/commits/{ref}").decode("utf-8"))
    return payload["sha"]


def download_tree(repo: str, commit: str) -> dict:
    """Return {relative_path: bytes} for every file under skills/ upstream."""
    blob = _fetch(f"{CODELOAD}/{repo}/tar.gz/{commit}")
    files = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            name = member.name.split("/", 1)[-1] if "/" in member.name else member.name
            if not name.startswith(UPSTREAM_PREFIX):
                continue
            relative = name[len(UPSTREAM_PREFIX):]
            if not relative or ".." in relative.split("/") or relative.startswith("."):
                continue
            handle = archive.extractfile(member)
            if handle is not None:
                files[relative] = handle.read()
    if not files:
        raise RuntimeError(f"no files found under {UPSTREAM_PREFIX} in {repo}@{commit[:12]}")
    return files


def scan_dest(dest: str) -> dict:
    present = {}
    for root, dirs, names in os.walk(dest):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in names:
            if name.startswith("."):
                continue
            path = os.path.join(root, name)
            relative = os.path.relpath(path, dest).replace(os.sep, "/")
            with open(path, "rb") as handle:
                present[relative] = hashlib.sha256(handle.read()).hexdigest()
    return present


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--dest", default=DEST)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"[sync-h3-skills] source: {args.repo}@{args.ref}  dest: {args.dest}")
    commit = resolve_commit(args.repo, args.ref)
    print(f"[sync-h3-skills] upstream commit: {commit[:12]}")
    upstream = download_tree(args.repo, commit)

    upstream_hashes = {path: hashlib.sha256(data).hexdigest() for path, data in upstream.items()}
    present = scan_dest(args.dest)

    added = sorted(p for p in upstream_hashes if p not in present)
    modified = sorted(p for p in upstream_hashes if p in present and upstream_hashes[p] != present[p])
    removed = sorted(p for p in present if p not in upstream_hashes)

    print(f"[sync-h3-skills] upstream files: {len(upstream_hashes)} | local: {len(present)}")
    for label, paths in (("新增", added), ("更新", modified), ("上游已删除", removed)):
        for path in paths:
            print(f"  [{label}] {path}")
    if not (added or modified or removed):
        meta_path = os.path.join(args.dest, SYNC_META)
        meta = {}
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf-8") as handle:
                meta = json.load(handle)
        if meta.get("commit") == commit:
            print("[sync-h3-skills] ✅ 已是最新，无需改动")
            return 0

    if args.dry_run:
        print(f"[sync-h3-skills] --dry-run：{len(added) + len(modified) + len(removed)} 个文件待同步，未改动")
        return 10

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(os.path.dirname(args.dest), f".h3_skills_backup_{stamp}")
    shutil.copytree(args.dest, backup)
    print(f"[sync-h3-skills] 旧版已备份到: {backup}")

    for path in removed:
        target = os.path.join(args.dest, *path.split("/"))
        os.remove(target)
        print(f"  [删除] {path}")
    for path in added + modified:
        target = os.path.join(args.dest, *path.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(upstream[path])
        print(f"  [写入] {path}")

    with open(os.path.join(args.dest, SYNC_META), "w", encoding="utf-8") as handle:
        json.dump({
            "repo": args.repo, "ref": args.ref, "commit": commit,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "files": len(upstream_hashes),
        }, handle, ensure_ascii=False, indent=2)

    skill_dirs = sorted({p.split("/")[0] for p in upstream if "/" in p})
    print(f"[sync-h3-skills] ✅ 同步完成：{len(added) + len(modified) + len(removed)} 个文件，"
          f"{len(skill_dirs)} 个技能目录")
    print("[sync-h3-skills] ⚠️ 新增/删除技能需重启 ComfyUI 才会进入下拉与路由目录；"
          "仅正文变化则下次运行即生效。")
    return 10


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"[sync-h3-skills] ❌ 失败：{error}", file=sys.stderr)
        sys.exit(2)
