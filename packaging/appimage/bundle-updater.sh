#!/usr/bin/env bash
# Put appimageupdatetool inside an AppDir so the app can update itself.
#
# Usage: bundle-updater.sh <AppDir>
#
# Downloads the appimageupdatetool AppImage for $ARCH, unpacks it without
# running it (so a cross-arch build works too), and copies only the binary and
# the libraries it links against into <AppDir>/usr/libexec/appimageupdatetool/
# (bin/ + lib/, stripped: ~6.5 MB instead of the tool's 36 MB AppImage).
# The app runs it as
#
#   LD_LIBRARY_PATH=$APPDIR/usr/libexec/appimageupdatetool/lib \
#     $APPDIR/usr/libexec/appimageupdatetool/bin/appimageupdatetool -O "$APPIMAGE"
#
# libc, libstdc++, libgcc_s, libz and libgpg-error come from the host, like in
# the upstream AppImage.
#
# Environment:
#   ARCH                  x86_64 | aarch64 (default: uname -m)
#   APPIMAGEUPDATETOOL    an already downloaded appimageupdatetool-<arch>.AppImage
#   APPIMAGEUPDATETOOL_URL  where to download it from (default: upstream continuous)
# Needs unsquashfs (apt install squashfs-tools) and readelf.
set -euo pipefail

appdir=${1:?AppDir required}
arch=${ARCH:-$(uname -m)}
dest="$appdir/usr/libexec/appimageupdatetool"

command -v unsquashfs >/dev/null || { echo "error: unsquashfs not found (install squashfs-tools), or set NO_UPDATER=1" >&2; exit 1; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

src=${APPIMAGEUPDATETOOL:-}
if [[ -z $src ]]; then
  src="$work/appimageupdatetool.AppImage"
  url=${APPIMAGEUPDATETOOL_URL:-https://github.com/AppImageCommunity/AppImageUpdate/releases/download/continuous/appimageupdatetool-$arch.AppImage}
  echo "Downloading appimageupdatetool from $url"
  curl -fsSL --retry 3 -o "$src" "$url"
fi

# The squashfs starts right after the runtime ELF: end of its section headers.
offset=$(python3 - "$src" <<'EOF'
import struct, sys
h = open(sys.argv[1], "rb").read(64)
assert h[:4] == b"\x7fELF", "not an ELF file"
if h[4] == 2:   # 64-bit
    shoff, = struct.unpack_from("<Q", h, 0x28); size, num = struct.unpack_from("<HH", h, 0x3A)
else:
    shoff, = struct.unpack_from("<I", h, 0x20); size, num = struct.unpack_from("<HH", h, 0x2E)
print(shoff + size * num)
EOF
)
unsquashfs -q -n -o "$offset" -d "$work/root" "$src" >/dev/null

# Copy the binary and its DT_NEEDED closure from the tool's own lib dirs.
rm -rf "$dest"
mkdir -p "$dest/bin" "$dest/lib"
cp -L "$work/root/usr/bin/appimageupdatetool" "$dest/bin/"
python3 - "$work/root" "$dest" <<'EOF'
import re, shutil, subprocess, sys
from pathlib import Path
root, dest = Path(sys.argv[1]), Path(sys.argv[2])
dirs = [root / "usr/lib", *sorted((root / "usr/lib").glob("*-linux-gnu"))]
todo, seen = [dest / "bin/appimageupdatetool"], set()
while todo:
    elf = todo.pop()
    out = subprocess.run(["readelf", "-d", str(elf)], capture_output=True, text=True, check=True).stdout
    for name in re.findall(r"\(NEEDED\).*\[(.+)\]", out):
        if name in seen:
            continue
        seen.add(name)
        for d in dirs:
            if (d / name).exists():
                shutil.copy2(d / name, dest / "lib" / name, follow_symlinks=True)
                todo.append(dest / "lib" / name)
                break
print("appimageupdatetool libs:", " ".join(sorted(p.name for p in (dest / "lib").iterdir())))
EOF
chmod -R u+w "$dest"
# Upstream ships them with debug info (libappimageupdate.so alone is 16 MB).
find "$dest" -type f -exec strip --strip-unneeded {} \; 2>/dev/null || true
# Keep the bundled libraries' copyright files.
[[ -d $work/root/usr/share/doc ]] && cp -r "$work/root/usr/share/doc" "$dest/doc"
du -sh "$dest"
