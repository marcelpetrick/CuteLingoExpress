#!/usr/bin/env bash
set -euo pipefail

bundle_dir="$1"
output_path="$2"
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work_dir="$(mktemp -d)"
trap 'rm -rf "${work_dir}"' EXIT

appdir="${work_dir}/CuteLingoExpress.AppDir"
mkdir -p "${appdir}/usr/lib/cutelingoexpress"
cp -a "${bundle_dir}/." "${appdir}/usr/lib/cutelingoexpress/"
cp "${repo_dir}/LICENSE" "${appdir}/LICENSE"
cp "${repo_dir}/media/logo.png" "${appdir}/cutelingoexpress.png"

cat > "${appdir}/AppRun" <<'APPRUN'
#!/bin/sh
appdir="$(dirname "$(readlink -f "$0")")"
exec "${appdir}/usr/lib/cutelingoexpress/cutelingoexpress" "$@"
APPRUN
chmod +x "${appdir}/AppRun"

cat > "${appdir}/cutelingoexpress.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=CuteLingoExpress
Exec=cutelingoexpress
Icon=cutelingoexpress
Terminal=true
Categories=Development;
DESKTOP

tool_version=1.9.1
runtime_version=20251108
curl -fsSL --retry 3 -o "${work_dir}/appimagetool" \
    "https://github.com/AppImage/appimagetool/releases/download/${tool_version}/appimagetool-x86_64.AppImage"
curl -fsSL --retry 3 -o "${work_dir}/runtime-x86_64" \
    "https://github.com/AppImage/type2-runtime/releases/download/${runtime_version}/runtime-x86_64"
(
    cd "${work_dir}"
    sha256sum --check <<'CHECKSUMS'
ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0  appimagetool
2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d  runtime-x86_64
CHECKSUMS
)
chmod +x "${work_dir}/appimagetool"
ARCH=x86_64 "${work_dir}/appimagetool" --appimage-extract-and-run \
    --runtime-file "${work_dir}/runtime-x86_64" "${appdir}" "${output_path}"
