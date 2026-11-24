#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
qt_root="${QT_ROOT_DIR:-${HOME}/Qt}"
qt_version="$(cat "${repo_dir}/.qt-version")"
qt_number="${qt_version//./}"
qt_dir="${qt_root}/${qt_version}/gcc_64"
base_url="https://download.qt.io/online/qtsdkrepository/linux_x64/desktop"
package_url="${base_url}/qt6_${qt_number}/qt6_${qt_number}/qt.qt6.${qt_number}.linux_gcc_64"

if [[ -x "${qt_dir}/bin/lrelease" ]] &&
    [[ "$("${qt_dir}/bin/lrelease" -version)" == "lrelease version ${qt_version}" ]]; then
    echo "Qt ${qt_version} Linguist tools are installed in ${qt_dir}."
    exit 0
fi

mkdir -p "$(dirname "${qt_dir}")"
work_dir="$(mktemp -d "${qt_root}/${qt_version}/.linguist-XXXXXX")"
trap 'rm -rf "${work_dir}"' EXIT
mkdir -p "${work_dir}/gcc_64/lib"

while read -r checksum archive; do
    curl -fsSL --retry 3 -o "${work_dir}/${archive}" "${package_url}/${archive}"
    (cd "${work_dir}" && printf '%s  %s\n' "${checksum}" "${archive}" | sha256sum --check)
    destination="${work_dir}/gcc_64"
    if [[ "${archive}" == *icu-* ]]; then
        destination="${destination}/lib"
    fi
    bsdtar -xpf "${work_dir}/${archive}" -C "${destination}"
    rm "${work_dir}/${archive}"
done < "${repo_dir}/packaging/qt-linux-x86_64.sha256"

[[ "$("${work_dir}/gcc_64/bin/lrelease" -version)" == "lrelease version ${qt_version}" ]]
mv -T "${work_dir}/gcc_64" "${qt_dir}"
echo "Installed Qt ${qt_version} Linguist tools in ${qt_dir}."
