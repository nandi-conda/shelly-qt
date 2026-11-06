#!/usr/bin/env bash
# fileapi forge job: build both AppImages on Depot's native amd64/arm64 builders
# (packaging/appimage/Dockerfile), then optionally publish them to GitHub.
#
# Env (from the forge): DEPOT_TOKEN (required), DEPOT_PROJECT_ID (optional; else the
# Depot project named shelly-qt is found or created), GH_TOKEN (optional; a GitHub token
# with Contents read/write on $GH_OWNER/$GH_REPO, publishes to the `continuous` release),
# FORGE_SHA, FORGE_BRANCH.
set -euo pipefail

APP_NAME=${APP_NAME:-Shelly-Qt}
GH_OWNER=${GH_OWNER:-nandi-conda}
GH_REPO=${GH_REPO:-shelly-qt}
CHANNEL=continuous
sha=${FORGE_SHA:-$(date +%s)}
version="0.1.0-g${sha:0:7}"

command -v depot >/dev/null || { echo "error: depot CLI not on PATH" >&2; exit 1; }
[[ -n ${DEPOT_TOKEN:-} ]] || { echo "error: DEPOT_TOKEN secret not set" >&2; exit 1; }

project=${DEPOT_PROJECT_ID:-}
if [[ -z $project ]]; then
  find_project() {
    local raw
    raw=$(depot projects list --output json 2>&1) || {
      echo "error: can't list Depot projects with this DEPOT_TOKEN ($raw)." >&2
      echo "       A project or org token can't look projects up: set the DEPOT_PROJECT_ID secret." >&2
      return 1
    }
    printf '%s' "$raw" | python3 -c '
import json, sys
d = json.load(sys.stdin)
if isinstance(d, dict):
    d = d.get("projects") or d.get("Projects") or []
for p in d:
    low = {k.lower(): v for k, v in p.items()}
    if low.get("name") == sys.argv[1]:
        print(low.get("projectid") or low.get("id")); break
' "$GH_REPO"
  }
  project=$(find_project) || exit 1
  if [[ -z $project ]]; then
    echo "Creating Depot project $GH_REPO"
    depot projects create "$GH_REPO" >/dev/null
    project=$(find_project)
  fi
  [[ -n $project ]] || { echo "error: no Depot project; set DEPOT_PROJECT_ID" >&2; exit 1; }
fi
echo "Depot project: $project  version: $version"

out=$(mktemp -d)
depot build --project "$project" --progress plain \
  --platform linux/amd64,linux/arm64 \
  -f packaging/appimage/Dockerfile \
  --build-arg VERSION="$version" --build-arg CHANNEL="$CHANNEL" \
  --build-arg APP_NAME="$APP_NAME" --build-arg GH_OWNER="$GH_OWNER" --build-arg GH_REPO="$GH_REPO" \
  --output "type=local,dest=$out" .

mkdir -p dist
find "$out" -type f -exec mv -t dist {} +
ls -la dist
cat dist/*.sha256

if [[ -z ${GH_TOKEN:-} ]]; then
  echo "GH_TOKEN not set: built and tested, not published."
  exit 0
fi

# Recreate the rolling `continuous` prerelease at this commit and upload the files.
python3 - "$GH_OWNER/$GH_REPO" "$sha" dist <<'PY'
import json, os, sys, urllib.error, urllib.request
from pathlib import Path
repo, sha, dist = sys.argv[1], sys.argv[2], Path(sys.argv[3])
tag = "continuous"
H = {"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json",
     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "fileapi-forge-shelly-qt"}

def call(method, url, body=None, headers=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method, headers={**H, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            txt = r.read()
            return r.status, json.loads(txt) if txt else None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")

api = f"https://api.github.com/repos/{repo}"
st, rel = call("GET", f"{api}/releases/tags/{tag}")
if st == 200:
    call("DELETE", f"{api}/releases/{rel['id']}")
st, _ = call("DELETE", f"{api}/git/refs/tags/{tag}")
st, rel = call("POST", f"{api}/releases", {
    "tag_name": tag, "target_commitish": sha, "name": "Continuous build", "prerelease": True,
    "body": f"Rolling build of {sha[:7]} (fileapi forge + Depot). Installed copies update with AppImageUpdate."})
if st != 201:
    sys.exit(f"create release failed: {st} {rel}")
upload = rel["upload_url"].split("{")[0]
for f in sorted(dist.iterdir()):
    if not f.name.endswith((".AppImage", ".zsync")):
        continue
    st, res = call("POST", f"{upload}?name={f.name}", raw=f.read_bytes(),
                   headers={"Content-Type": "application/octet-stream"})
    if st != 201:
        sys.exit(f"upload {f.name} failed: {st} {res}")
    print("uploaded", res["browser_download_url"])
print("release:", rel["html_url"])
PY
