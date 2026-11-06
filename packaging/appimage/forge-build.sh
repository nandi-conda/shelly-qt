#!/usr/bin/env bash
# fileapi forge job: build both AppImages on Depot's native amd64/arm64 builders
# (packaging/appimage/Dockerfile), then publish them as a release of this fileapi repo.
#
#   push to main -> rolling `continuous` prerelease (recreated at this commit)
#   tag v*       -> release <tag>
#
# Env (from the forge): DEPOT_TOKEN (required), DEPOT_PROJECT_ID (optional; else the
# Depot project named shelly-qt is found or created, which needs a user token),
# FORGE_SHA, FORGE_TAG, FORGE_TOKEN (+ forge-release on PATH).
#
# The embedded update info still points at the GitHub releases (built by GitHub
# Actions): AppImageUpdate's zsync needs HTTP range requests, which fileapi's asset
# downloads don't serve yet.
set -euo pipefail

APP_NAME=${APP_NAME:-Shelly-Qt}
GH_OWNER=${GH_OWNER:-nandi-conda}
GH_REPO=${GH_REPO:-shelly-qt}
sha=${FORGE_SHA:-$(date +%s)}
if [[ -n ${FORGE_TAG:-} ]]; then
  tag=$FORGE_TAG; version=${FORGE_TAG#v}; CHANNEL=latest
else
  tag=continuous; version="0.1.0-g${sha:0:7}"; CHANNEL=continuous
fi

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
  --build-arg VERSION="$version" --build-arg CHANNEL="$CHANNEL" --build-arg COMMIT="${FORGE_SHA:-}" \
  --build-arg APP_NAME="$APP_NAME" --build-arg GH_OWNER="$GH_OWNER" --build-arg GH_REPO="$GH_REPO" \
  --output "type=local,dest=$out" .

mkdir -p dist
find "$out" -type f -exec mv -t dist {} +
ls -la dist
cat dist/*.sha256

command -v forge-release >/dev/null || { echo "error: forge-release not on PATH (old fileapi?)" >&2; exit 1; }
if [[ $tag == continuous ]]; then
  forge-release delete continuous 2>/dev/null || true
  forge-release create continuous --prerelease --ref "$sha" --title "Continuous build" \
    --notes "Rolling build of ${sha:0:7} on Depot. Built by the fileapi forge job \`appimage\`."
else
  forge-release create "$tag" --ref "$sha" --title "Shelly-Qt $tag" 2>/dev/null || true
fi
forge-release upload "$tag" dist/*
echo "Published: ${FORGE_URL:-https://fileapi.fastapicloud.dev}/forge/#${FORGE_REPO:-nandi.uk/shelly-qt} (Releases, $tag)"
