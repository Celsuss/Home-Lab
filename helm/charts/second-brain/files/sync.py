#!/usr/bin/env python3
"""Reconcile the org-roam second brain into an Open WebUI knowledge base.

Reads a git clone of the notes repo and drives Open WebUI's incremental sync
API (`POST /api/v1/knowledge/{id}/sync/diff`), which does the diffing server
side: we send a `{path, filename, checksum}` manifest and it tells us what to
add, replace and delete. Unmodified notes cost nothing, so this is cheap to run
hourly.

Stdlib only, on purpose. `helm/charts/mcpo/README.md` records what happens when
a pod resolves its dependencies at start-up: a registry hiccup leaves a running
pod that silently serves nothing. Hand-rolling ~20 lines of multipart is the
cheaper trade.

Environment:
  OPEN_WEBUI_URL        base URL, e.g. http://open-webui.ai-workloads.svc.cluster.local:8080
  OPEN_WEBUI_API_KEY    admin API key (sk-...)
  KB_NAME               knowledge base name (created if absent)
  KB_DESCRIPTION        description used only at creation time
  REPO_DIR              where the clone lives (default /repo)
  NOTES_SUBDIR          subtree to index (default org-roam)
  GIT_URL               clone URL without credentials; empty = use REPO_DIR as-is
  GIT_BRANCH            branch to track (default master)
  GIT_USERNAME          Forgejo user for HTTP basic auth
  GIT_TOKEN             Forgejo token, read:repository scope
  INSECURE_TLS          "1" to skip cert verification (local runs against the homelab CA)
"""

import argparse
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

BASE = os.environ.get("OPEN_WEBUI_URL", "").rstrip("/")
API_KEY = os.environ.get("OPEN_WEBUI_API_KEY", "")
KB_NAME = os.environ.get("KB_NAME", "Second Brain")
KB_DESCRIPTION = os.environ.get(
    "KB_DESCRIPTION", "org-roam second brain, synced from git. Managed by the second-brain chart."
)
REPO_DIR = Path(os.environ.get("REPO_DIR", "/repo"))
NOTES_SUBDIR = os.environ.get("NOTES_SUBDIR", "org-roam")

GIT_URL = os.environ.get("GIT_URL", "")
GIT_BRANCH = os.environ.get("GIT_BRANCH", "master")
GIT_USERNAME = os.environ.get("GIT_USERNAME", "")
GIT_TOKEN = os.environ.get("GIT_TOKEN", "")

SSL_CTX = ssl._create_unverified_context() if os.environ.get("INSECURE_TLS") == "1" else None

# Directories and filename shapes that are never notes: LaTeX preview images,
# Emacs backups (`foo.org~`), auto-saves (`.#foo.org`) and lock leftovers
# (`foo.org#`).
SKIP_DIRS = {"ltximg", ".git"}

ORG_ID_LINK = re.compile(r"\[\[id:([0-9A-Fa-f-]{36})\](?:\[(.*?)\])?\]", re.S)
ORG_ID_PROP = re.compile(r"^:ID:\s+(\S+)\s*$", re.M)
ORG_TITLE = re.compile(r"^#\+title:\s*(.+?)\s*$", re.M | re.I)
ORG_ALIASES = re.compile(r"^:ROAM_ALIASES:\s*(.+?)\s*$", re.M | re.I)
ORG_FILETAGS = re.compile(r"^#\+filetags:\s*(.+?)\s*$", re.M | re.I)


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


def run(args, **kwargs):
    """Run a git command, raising with stderr attached on failure.

    Credentials never reach argv or the remote URL — see fetch_repo.
    """
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout.strip()


def fetch_repo():
    """Bring REPO_DIR to origin/GIT_BRANCH, cloning on first run.

    The token is passed through a one-shot askpass script rather than embedded
    in the remote URL, so it never lands in .git/config on the PVC, in argv, or
    in an error message echoing the URL.
    """
    if not GIT_URL:
        log(f"GIT_URL unset — using {REPO_DIR} as-is")
        return

    askpass = Path("/tmp/askpass.sh")
    askpass.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        '  Username*) printf %s "$GIT_USERNAME" ;;\n'
        '  Password*) printf %s "$GIT_TOKEN" ;;\n'
        "esac\n"
    )
    askpass.chmod(0o700)
    env = {
        **os.environ,
        "GIT_ASKPASS": str(askpass),
        "GIT_TERMINAL_PROMPT": "0",
    }

    if (REPO_DIR / ".git").is_dir():
        run(["git", "-C", str(REPO_DIR), "fetch", "--depth", "1", "origin", GIT_BRANCH], env=env)
        run(["git", "-C", str(REPO_DIR), "reset", "--hard", "FETCH_HEAD"])
        # A shallow fetch leaves the previous tip unreferenced, so the repo
        # grows by a pack every run. In the cluster REPO_DIR is an emptyDir and
        # this branch never runs, but it keeps the script correct against any
        # persistent checkout.
        run(["git", "-C", str(REPO_DIR), "reflog", "expire", "--expire=now", "--all"])
        run(["git", "-C", str(REPO_DIR), "gc", "--prune=now", "--quiet"])
    else:
        REPO_DIR.mkdir(parents=True, exist_ok=True)
        run(
            ["git", "clone", "--depth", "1", "--branch", GIT_BRANCH, GIT_URL, str(REPO_DIR)],
            env=env,
        )

    head = run(["git", "-C", str(REPO_DIR), "rev-parse", "--short", "HEAD"])
    log(f"repo at {GIT_BRANCH} {head}")


# ---------------------------------------------------------------------------
# org parsing and transformation
# ---------------------------------------------------------------------------


def is_note(path: Path) -> bool:
    if path.suffix != ".org":
        return False
    if path.name.startswith(".#"):
        return False
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    return True


def iter_notes(root: Path):
    """Yield note paths under root, sorted so runs are reproducible."""
    for path in sorted(root.rglob("*")):
        # rglob("*.org") would miss nothing, but globbing everything lets
        # is_note own all the exclusion rules in one place.
        if path.is_file() and is_note(path):
            yield path


def parse_note(text: str):
    id_match = ORG_ID_PROP.search(text)
    title_match = ORG_TITLE.search(text)
    aliases_match = ORG_ALIASES.search(text)
    tags_match = ORG_FILETAGS.search(text)
    return {
        "id": id_match.group(1) if id_match else "",
        "title": title_match.group(1) if title_match else "",
        "aliases": re.findall(r'"([^"]+)"', aliases_match.group(1)) if aliases_match else [],
        "tags": [t for t in (tags_match.group(1).split(":") if tags_match else []) if t],
    }


def transform(text: str, meta: dict, relpath: str, id_to_title: dict) -> bytes:
    """Rewrite roam id-links to titles and prepend an identity preamble.

    The link rewrite is the highest-value step here: a retrieved chunk full of
    raw UUIDs tells a model nothing, whereas the titles of neighbouring notes
    give it something to ask for next. The preamble makes the *first* chunk of
    every note carry its own name, aliases and tags, which is what the vector
    search actually matches against.
    """

    def replace(match):
        target_id, description = match.group(1), match.group(2)
        label = description or id_to_title.get(target_id) or "unknown note"
        return f"[[{label}]]"

    body = ORG_ID_LINK.sub(replace, text)

    preamble = [f"Note: {meta['title'] or Path(relpath).stem}"]
    if meta["aliases"]:
        preamble.append(f"Also known as: {', '.join(meta['aliases'])}")
    if meta["tags"]:
        preamble.append(f"Tags: {', '.join(meta['tags'])}")
    preamble.append(f"Source: {relpath}")

    return ("\n".join(preamble) + "\n\n" + body).encode("utf-8")


def build_manifest(limit=None):
    """Read every note once, returning manifest entries plus upload payloads."""
    notes_root = REPO_DIR / NOTES_SUBDIR
    if not notes_root.is_dir():
        sys.exit(f"{notes_root} does not exist — is REPO_DIR/NOTES_SUBDIR right?")

    paths = list(iter_notes(notes_root))
    if limit:
        paths = paths[:limit]

    raw = {}
    for path in paths:
        try:
            raw[path] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            log(f"  skipping {path} — not valid UTF-8")

    # One pass to learn every id → title before rewriting any links.
    parsed = {path: parse_note(text) for path, text in raw.items()}
    id_to_title = {m["id"]: m["title"] for m in parsed.values() if m["id"] and m["title"]}

    entries = []
    for path, text in raw.items():
        relpath = path.relative_to(REPO_DIR).as_posix()
        content = transform(text, parsed[path], relpath, id_to_title)
        # Path.relative_to renders "same directory" as ".", but the sync API
        # wants "" for the root of the knowledge base.
        subdir = path.parent.relative_to(notes_root).as_posix()
        entries.append(
            {
                "path": "" if subdir == "." else subdir,
                "filename": path.name,
                # Hash what we upload, not what is on disk — otherwise every
                # run sees a mismatch against the stored file_hash and
                # re-uploads the entire corpus.
                "checksum": hashlib.sha256(content).hexdigest(),
                "size": len(content),
                "content": content,
            }
        )
    log(f"read {len(entries)} notes, {len(id_to_title)} with resolvable ids")
    return entries


# ---------------------------------------------------------------------------
# Open WebUI API
# ---------------------------------------------------------------------------


def request(path, method="GET", body=None, timeout=120, raw_body=None, content_type=None):
    url = BASE + path
    if raw_body is not None:
        data = raw_body
    elif body is not None:
        data = json.dumps(body).encode()
        content_type = "application/json"
    else:
        data = None

    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + API_KEY)
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"{method} {path} → {exc.code}: {detail}") from None


def wait_for_open_webui(attempts=60, delay=5):
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(BASE + "/health")
            with urllib.request.urlopen(req, timeout=10, context=SSL_CTX):
                return
        except Exception as exc:  # noqa: BLE001 — any failure means "not up yet"
            log(f"waiting for Open WebUI ({attempt}/{attempts}): {exc}")
            time.sleep(delay)
    sys.exit(f"Open WebUI at {BASE} never became ready")


def ensure_knowledge_base(dry_run=False):
    existing = request("/api/v1/knowledge/").get("items") or []
    for item in existing:
        if item.get("name") == KB_NAME:
            return item["id"]
    if dry_run:
        return None
    created = request(
        "/api/v1/knowledge/create",
        method="POST",
        body={"name": KB_NAME, "description": KB_DESCRIPTION, "data": {}},
    )
    log(f"created knowledge base {KB_NAME!r} ({created['id']})")
    return created["id"]


def upload_note(entry, kb_id, directory_id):
    """Upload one note, extracting and embedding it straight into the KB.

    `knowledge_id` in the metadata makes Open WebUI link and embed the file
    into the knowledge base itself (routers/files.py:227-252), which saves a
    second `files/batch/add` round-trip. `process_in_background=false` makes
    the call synchronous, so slow embeddings apply backpressure here instead
    of piling up inside the Open WebUI pod.
    """
    metadata = {"file_hash": entry["checksum"], "knowledge_id": kb_id}
    if directory_id:
        metadata["directory_id"] = directory_id

    boundary = "----second-brain-" + uuid.uuid4().hex
    parts = bytearray()
    parts += (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="metadata"\r\n\r\n'
        f"{json.dumps(metadata)}\r\n"
    ).encode()
    parts += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{entry["filename"]}"\r\n'
        # Declaring text/plain puts the file on the TextLoader path explicitly
        # rather than relying on the loader's catch-all else branch.
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
    ).encode()
    parts += entry["content"]
    parts += f"\r\n--{boundary}--\r\n".encode()

    return request(
        "/api/v1/files/?process=true&process_in_background=false",
        method="POST",
        raw_body=bytes(parts),
        content_type=f"multipart/form-data; boundary={boundary}",
        timeout=300,
    )


def create_directories(kb_id, mkdir_paths, directory_map):
    # sync/diff returns these parent-first, but sorting by depth again makes
    # the invariant local rather than an assumption about the server.
    for dir_path in sorted(mkdir_paths, key=lambda p: p.count("/")):
        name = dir_path.rsplit("/", 1)[-1]
        parent = dir_path.rsplit("/", 1)[0] if "/" in dir_path else ""
        created = request(
            f"/api/v1/knowledge/{kb_id}/dirs/create",
            method="POST",
            body={"name": name, "parent_id": directory_map.get(parent)},
        )
        directory_map[dir_path] = created["id"]
        log(f"created directory {dir_path!r}")


# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report the diff, change nothing")
    parser.add_argument("--limit", type=int, help="only consider the first N notes (smoke tests)")
    args = parser.parse_args()

    if not BASE or not API_KEY:
        sys.exit("OPEN_WEBUI_URL and OPEN_WEBUI_API_KEY are required")

    fetch_repo()
    wait_for_open_webui()

    entries = build_manifest(limit=args.limit)
    by_key = {(e["path"], e["filename"]): e for e in entries}

    kb_id = ensure_knowledge_base(dry_run=args.dry_run)
    manifest = [
        {"path": e["path"], "filename": e["filename"], "checksum": e["checksum"], "size": e["size"]}
        for e in entries
    ]

    if kb_id is None:
        # Dry run against a knowledge base that does not exist yet. Creating one
        # just to diff against it would be a write, so report the obvious.
        log(f"knowledge base {KB_NAME!r} does not exist — would create it and add all {len(entries)} notes")
        return

    diff = request(f"/api/v1/knowledge/{kb_id}/sync/diff", method="POST", body={"manifest": manifest})

    log(
        f"diff: added={len(diff['added'])} modified={len(diff['modified'])} "
        f"deleted={len(diff['deleted'])} unmodified={diff['unmodified_count']} "
        f"mkdir={len(diff['mkdir'])} rmdir={len(diff['rmdir'])}"
    )

    if args.dry_run:
        log("dry run — nothing uploaded")
        return

    directory_map = dict(diff.get("directory_map") or {})
    create_directories(kb_id, diff["mkdir"], directory_map)

    # Drop the stale copies of modified notes *before* re-uploading, so a note
    # never exists twice in the vector store even if this run dies midway.
    stale = [m["stale_file_id"] for m in diff["modified"]]
    removals = [d["file_id"] for d in diff["deleted"]] + stale
    if removals or diff["rmdir"]:
        request(
            f"/api/v1/knowledge/{kb_id}/sync/cleanup",
            method="POST",
            body={"file_ids": removals, "dir_ids": diff["rmdir"]},
            timeout=300,
        )
        log(f"removed {len(removals)} stale files, {len(diff['rmdir'])} directories")

    pending = [
        by_key[(item["path"], item["filename"])]
        for item in diff["added"] + diff["modified"]
        if (item["path"], item["filename"]) in by_key
    ]
    failures = []
    for index, entry in enumerate(pending, start=1):
        try:
            upload_note(entry, kb_id, directory_map.get(entry["path"]))
        except Exception as exc:  # noqa: BLE001 — collect and report, don't abort the run
            failures.append((entry["filename"], str(exc)))
        if index % 50 == 0 or index == len(pending):
            log(f"uploaded {index}/{len(pending)}")

    for filename, error in failures[:10]:
        log(f"FAILED {filename}: {error}")

    # Open WebUI answers 200 even when background extraction fails, so the only
    # honest check is to ask it again what it thinks is missing.
    verify = request(f"/api/v1/knowledge/{kb_id}/sync/diff", method="POST", body={"manifest": manifest})
    residual = len(verify["added"]) + len(verify["modified"])
    log(
        f"result: uploaded={len(pending) - len(failures)} failed={len(failures)} "
        f"removed={len(removals)} in_sync={verify['unmodified_count']} residual={residual}"
    )
    if residual or failures:
        sys.exit(f"{residual} notes still out of sync after this run")


if __name__ == "__main__":
    main()
