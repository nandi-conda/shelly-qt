#!/usr/bin/env bash
# Turn an AppDir into an AppImage with embedded update info and a .zsync file.
#
# Usage:
#   make-appimage.sh <AppDir> <output.AppImage> <update-info>
#
# Example:
#   make-appimage.sh build/MyApp.AppDir dist/MyApp-1.2.3-x86_64.AppImage \
#     "gh-releases-zsync|owner|repo|latest|MyApp-*-x86_64.AppImage.zsync"
#
# Environment:
#   ARCH              x86_64 | aarch64 (default: uname -m)
#   APPIMAGETOOL      path to an appimagetool binary (default: download pinned)
#   APPIMAGETOOL_URL  where to download it from (default: continuous build)
#   RUNTIME_FILE      optional type2 runtime to embed (--runtime-file)
#   NO_APPSTREAM=1    skip AppStream validation (-n)
#   SIGN_KEY          optional GPG key id; signs the AppImage
set -euo pipefail

appdir=${1:?AppDir required}
out=${2:?output path required}
updinfo=${3:?update info required}

export ARCH=${ARCH:-$(uname -m)}
export APPIMAGE_EXTRACT_AND_RUN=1   # CI runners have no FUSE

tooldir=${TOOLDIR:-${RUNNER_TEMP:-/tmp}/appimage-tools}
mkdir -p "$tooldir" "$(dirname "$out")"

if [[ -z ${APPIMAGETOOL:-} ]]; then
  host_arch=$(uname -m)
  APPIMAGETOOL="$tooldir/appimagetool-$host_arch.AppImage"
  url=${APPIMAGETOOL_URL:-https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$host_arch.AppImage}
  if [[ ! -x $APPIMAGETOOL ]]; then
    echo "Downloading appimagetool from $url"
    curl -fsSL --retry 3 -o "$APPIMAGETOOL" "$url"
    chmod +x "$APPIMAGETOOL"
  fi
fi

# Sanity checks that appimagetool reports badly or not at all.
[[ -x $appdir/AppRun ]] || { echo "error: $appdir/AppRun missing or not executable" >&2; exit 1; }
mapfile -t desktops < <(find "$appdir" -maxdepth 1 -name '*.desktop')
[[ ${#desktops[@]} -eq 1 ]] || { echo "error: need exactly one .desktop at the AppDir root, found ${#desktops[@]}" >&2; exit 1; }
icon=$(sed -n 's/^Icon=//p' "${desktops[0]}" | head -n1)
compgen -G "$appdir/$icon.*" >/dev/null || { echo "error: icon '$icon' (.svg/.png) not at AppDir root" >&2; exit 1; }
case $updinfo in
  gh-releases-zsync\|*\|*\|*\|*.zsync) ;;
  zsync\|http*) ;;
  *) echo "error: update info looks wrong: $updinfo" >&2; exit 1 ;;
esac

args=(--updateinformation "$updinfo")
[[ -n ${RUNTIME_FILE:-} ]] && args+=(--runtime-file "$RUNTIME_FILE")
[[ ${NO_APPSTREAM:-0} == 1 ]] && args+=(-n)
[[ -n ${SIGN_KEY:-} ]] && args+=(--sign --sign-key "$SIGN_KEY")

rm -f "$out" "$out.zsync"
"$APPIMAGETOOL" "${args[@]}" "$appdir" "$out"

# appimagetool writes <out>.zsync next to the output when update info is set.
# Older builds may drop it in the current directory or skip it; cover both.
if [[ ! -f $out.zsync ]]; then
  base=$(basename "$out")
  if [[ -f $base.zsync && $base.zsync != "$out.zsync" ]]; then
    mv "$base.zsync" "$out.zsync"
  else
    command -v zsyncmake >/dev/null || { echo "error: no .zsync produced and zsyncmake not installed (apt install zsync)" >&2; exit 1; }
    (cd "$(dirname "$out")" && zsyncmake -u "$base" -o "$base.zsync" "$base")
  fi
fi

# The .zsync URL must be the bare filename so it resolves next to the .zsync.
url_line=$(grep -a -m1 '^URL:' "$out.zsync" | cut -d' ' -f2-)
if [[ $url_line != "$(basename "$out")" ]]; then
  echo "warning: .zsync URL is '$url_line', expected '$(basename "$out")'" >&2
fi

# Read the ELF section directly: with APPIMAGE_EXTRACT_AND_RUN=1 the runtime
# passes --appimage-updateinformation through to the app instead of answering.
embedded=$(readelf -p .upd_info "$out" 2>/dev/null | sed -n 's/^ *\[ *0\] *//p' | head -n1)
if [[ $embedded != "$updinfo" ]]; then
  echo "error: embedded update info '$embedded' != '$updinfo'" >&2
  exit 1
fi

echo "Built $out"
echo "      $out.zsync"
echo "Update info: $embedded"
