# Build and smoke-test the Shelly-Qt AppImage for the target platform, then
# export only dist/ (use with `--output type=local,dest=out`).
#
#   depot build --platform linux/amd64,linux/arm64 -f packaging/appimage/Dockerfile \
#     --build-arg VERSION=1.2.3 --build-arg CHANNEL=continuous --output type=local,dest=out .
#
# Each platform builds natively on its own Depot builder, so ARCH is uname -m.
FROM public.ecr.aws/ubuntu/ubuntu:22.04 AS build

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl python3 binutils file zsync squashfs-tools desktop-file-utils appstream \
      libopengl0 libgl1 libegl1 libglx0 libfontconfig1 libxkbcommon0 xvfb xauth \
    && rm -rf /var/lib/apt/lists/*

ARG PIXI_VERSION=latest
RUN curl -fsSL https://pixi.sh/install.sh | PIXI_VERSION=$PIXI_VERSION PIXI_HOME=/usr/local bash \
    && pixi --version

WORKDIR /src
COPY . .

ARG VERSION=dev
ARG CHANNEL=continuous
# The last RUN also smoke-tests: update info, --version, the bundled updater, and the GUI
# staying up for 10 s on X11 against the fake CLI.
ARG APP_NAME=Shelly-Qt
ARG GH_OWNER=nandi-conda
ARG GH_REPO=shelly-qt

RUN --mount=type=cache,target=/root/.cache/rattler,sharing=locked \
    --mount=type=cache,target=/tmp/appimage-tools,sharing=locked \
    set -eux; \
    export ARCH=$(uname -m) PIXI_LOCKED=1 QT_QPA_PLATFORM=offscreen TOOLDIR=/tmp/appimage-tools; \
    file="$APP_NAME-$VERSION-$ARCH.AppImage"; \
    export RUNTIME_FILE=/tmp/appimage-tools/runtime-$ARCH; \
    [ -s "$RUNTIME_FILE" ] || curl -fsSL --retry 3 -o "$RUNTIME_FILE" \
      "https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-$ARCH"; \
    packaging/appimage/build-appdir.sh "build/$APP_NAME.AppDir"; \
    packaging/appimage/make-appimage.sh "build/$APP_NAME.AppDir" "dist/$file" \
      "gh-releases-zsync|$GH_OWNER|$GH_REPO|$CHANNEL|$APP_NAME-*-$ARCH.AppImage.zsync"; \
    export APPIMAGE_EXTRACT_AND_RUN=1; \
    readelf -p .upd_info "dist/$file"; \
    "./dist/$file" --version; \
    tool="build/$APP_NAME.AppDir/usr/libexec/appimageupdatetool"; \
    LD_LIBRARY_PATH=$tool/lib "$tool/bin/appimageupdatetool" --version; \
    LD_LIBRARY_PATH=$tool/lib "$tool/bin/appimageupdatetool" --describe "dist/$file"; \
    rc=0; SHELLY_BIN="python3 $PWD/tests/fake_shelly.py" SHELLY_ELEVATE="" \
      timeout 10 xvfb-run -a "./dist/$file" || rc=$?; \
    [ "$rc" -eq 124 ] || { echo "AppImage exited early with $rc"; exit 1; }; \
    (cd dist && sha256sum * > "$file.sha256"); \
    ls -la dist

FROM scratch
COPY --from=build /src/dist/ /
