#!/usr/bin/env python3
"""Publish the working tree to GitHub through the REST API.

Useful when direct HTTPS git access to github.com is blocked but
api.github.com is reachable.

    set GITHUB_TOKEN=ghp_xxx
    python tools/publish_github.py --repo owner/name --message "update"

Nothing is deleted on the remote: files are added or replaced.
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error

API = "https://api.github.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message", default="update from local tree")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        # .env in the repository root: GITHUB_TOKEN=xxx
        env_path = os.path.join(ROOT, ".env")
        if os.path.isfile(env_path):
            for line in open(env_path, encoding="utf-8"):
                line = line.strip()
                if line.startswith("GITHUB_TOKEN=") or line.startswith("GH_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not token:
        print("GITHUB_TOKEN is not set (env var or .env)")
        return 2

    def call(method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(API + path, data=data, method=method,
                                     headers={"Authorization": "token " + token,
                                              "Accept": "application/vnd.github+json",
                                              "User-Agent": "sunloom-publish"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            return e.code, {"raw": e.read().decode("utf-8", "ignore")[:400]}

    st, ref = call("GET", "/repos/%s/git/ref/heads/%s" % (args.repo, args.branch))
    if st != 200:
        print("cannot read branch %s: %s" % (args.branch, ref.get("raw")))
        return 1
    parent = ref["object"]["sha"]
    st, c = call("GET", "/repos/%s/git/commits/%s" % (args.repo, parent))
    base_tree = c["tree"]["sha"]

    raw = subprocess.run(["git", "-C", ROOT, "ls-files", "-z"], capture_output=True).stdout
    files = [x.decode("utf-8") for x in raw.split(b"\x00") if x]

    entries = []
    for f in files:
        p = os.path.join(ROOT, f.replace("/", os.sep))
        st, blob = call("POST", "/repos/%s/git/blobs" % args.repo,
                        {"content": base64.b64encode(open(p, "rb").read()).decode(),
                         "encoding": "base64"})
        if st not in (200, 201):
            print("blob failed:", f, st, blob)
            return 1
        entries.append({"path": f, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    print("files:", len(entries))

    st, tree = call("POST", "/repos/%s/git/trees" % args.repo,
                    {"tree": entries, "base_tree": base_tree})
    if st not in (200, 201):
        print("tree failed:", st, tree)
        return 1

    st, commit = call("POST", "/repos/%s/git/commits" % args.repo,
                      {"message": args.message, "tree": tree["sha"], "parents": [parent]})
    if st not in (200, 201):
        print("commit failed:", st, commit)
        return 1
    print("commit:", commit["sha"])

    if args.dry_run:
        print("dry run, ref not updated")
        return 0
    st, r = call("PATCH", "/repos/%s/git/refs/heads/%s" % (args.repo, args.branch),
                 {"sha": commit["sha"]})
    print("ref:", st)
    return 0 if st == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
