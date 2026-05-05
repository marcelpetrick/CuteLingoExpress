#!/usr/bin/env bash
set -u
set -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON="${VENV_DIR}/bin/python"
PIPELINE_LOG_DIR="${TMPDIR:-/tmp}/CuteLingoExpress-pipeline-$$"
trap 'rm -rf "${PIPELINE_LOG_DIR}"' EXIT

declare -a SUMMARY_LINES=()

VENV_OK=0
INSTALL_OK=0
VERSION_OK=0
PYLINT_OK=0
TESTS_OK=0
CLEAN_OK=0
BUILD_OK=0
WHEEL_OK=0
PACKAGE_INSTALL_OK=0
IMPORT_OK=0

PYLINT_DETAILS=""
TESTS_DETAILS=""
BUILD_DETAILS=""
WHEEL_DETAILS=""
IMPORT_DETAILS=""

print_usage() {
    cat <<EOF
Usage: ./localPipeline.sh [--noRun]

Local project pipeline:
  1. Create or reuse .venv
  2. Install the project with development dependencies from pyproject.toml
  3. Verify the runtime version command
  4. Run Pylint static analysis
  5. Run unittest with coverage and generate htmlcov/index.html
  6. Remove stale package build artifacts
  7. Build source and wheel distributions
  8. Install the freshly built wheel into .venv
  9. Verify that the installed package exposes the expected version
  10. Print a final stage-by-stage summary

--noRun is accepted for compatibility with other local pipeline scripts. This
project has no long-running application launch stage, so it currently has no
effect.
EOF
}

log() {
    printf '[INFO] %s\n' "$*"
}

warn() {
    printf '[WARN] %s\n' "$*" >&2
}

error() {
    printf '[ERROR] %s\n' "$*" >&2
}

mark_result() {
    local label="$1"
    local status="$2"
    local details="$3"
    SUMMARY_LINES+=("$(printf '%-16s : %-4s %s' "${label}" "${status}" "${details}")")
}

run_with_log() {
    local log_path="$1"
    shift

    mkdir -p "${PIPELINE_LOG_DIR}"
    "$@" 2>&1 | tee "${log_path}"
    return "${PIPESTATUS[0]}"
}

extract_pylint_details() {
    local log_path="$1"
    local score_line
    local score

    score_line="$(grep -E "rated at [-0-9.]+/10" "${log_path}" | tail -n 1 || true)"
    if [[ -n "${score_line}" ]]; then
        score="${score_line#*rated at }"
        score="${score%% *}"
        awk -v score="${score}" 'BEGIN { split(score, parts, "/"); printf "%s (%.0f%%)\n", score, parts[1] / parts[2] * 100 }'
        return
    fi

    printf '%s\n' "see Pylint output"
}

extract_test_details() {
    local log_path="$1"
    local result_line
    local coverage_line

    result_line="$(grep -E "Ran [0-9]+ tests? in " "${log_path}" | tail -n 1 || true)"
    coverage_line="$(grep -E "^TOTAL[[:space:]]+" "${log_path}" | tail -n 1 || true)"

    if [[ -n "${result_line}" && -n "${coverage_line}" ]]; then
        printf '%s; %s\n' "${result_line}" "${coverage_line}"
        return
    fi
    if [[ -n "${result_line}" ]]; then
        printf '%s\n' "${result_line}"
        return
    fi

    printf '%s\n' "see unittest and coverage output"
}

extract_build_details() {
    local log_path="$1"
    local built_line

    built_line="$(grep -E "Successfully built " "${log_path}" | tail -n 1 || true)"
    if [[ -n "${built_line}" ]]; then
        printf '%s\n' "${built_line}"
        return
    fi

    printf '%s\n' "source and wheel distributions built"
}

print_summary() {
    printf '\n========== Local Pipeline Summary ==========\n'
    local line
    for line in "${SUMMARY_LINES[@]}"; do
        printf '%s\n' "${line}"
    done
    printf '============================================\n'
}

parse_arguments() {
    local argument
    for argument in "$@"; do
        case "${argument}" in
            --noRun)
                warn "--noRun accepted; this project has no launch stage."
                ;;
            --help|-h)
                print_usage
                exit 0
                ;;
            *)
                error "Unknown argument: ${argument}"
                print_usage
                exit 2
                ;;
        esac
    done
}

prepare_virtual_environment() {
    if [[ -x "${PYTHON}" ]]; then
        log "Using existing virtual environment: ${VENV_DIR}"
        return 0
    fi

    log "Creating virtual environment: ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}"
}

install_development_dependencies() {
    log "Installing project with development dependencies."
    "${PYTHON}" -m pip install -e ".[dev]"
}

verify_runtime_version() {
    log "Verifying runtime version command."
    local version_output

    version_output="$("${PYTHON}" "${ROOT_DIR}/auto_trans.py" --version)"
    printf '%s\n' "${version_output}"

    if [[ "${version_output}" == "CuteLingoExpress "* ]]; then
        return 0
    fi

    return 1
}

run_pylint() {
    log "Running Pylint static analysis."
    local log_path="${PIPELINE_LOG_DIR}/pylint.log"

    if run_with_log "${log_path}" "${PYTHON}" -m pylint auto_trans.py test_auto_trans.py version.py; then
        PYLINT_DETAILS="$(extract_pylint_details "${log_path}")"
        return 0
    fi

    PYLINT_DETAILS="$(extract_pylint_details "${log_path}")"
    return 1
}

run_tests_with_coverage() {
    log "Running unittest with coverage."
    local log_path="${PIPELINE_LOG_DIR}/coverage.log"

    if run_with_log "${log_path}" "${PYTHON}" -m coverage run -m unittest; then
        "${PYTHON}" -m coverage report -m 2>&1 | tee -a "${log_path}"
        local report_status="${PIPESTATUS[0]}"
        "${PYTHON}" -m coverage html 2>&1 | tee -a "${log_path}"
        local html_status="${PIPESTATUS[0]}"
        TESTS_DETAILS="$(extract_test_details "${log_path}")"
        [[ "${report_status}" -eq 0 && "${html_status}" -eq 0 ]]
        return
    fi

    TESTS_DETAILS="$(extract_test_details "${log_path}")"
    return 1
}

clean_package_artifacts() {
    log "Removing stale package build artifacts."
    rm -rf "${ROOT_DIR}/build" "${ROOT_DIR}/dist" "${ROOT_DIR}/cutelingoexpress.egg-info"
}

build_package() {
    log "Building source and wheel distributions."
    local log_path="${PIPELINE_LOG_DIR}/build.log"

    if run_with_log "${log_path}" "${PYTHON}" -m build; then
        BUILD_DETAILS="$(extract_build_details "${log_path}")"
        return 0
    fi

    BUILD_DETAILS="package build failed"
    return 1
}

find_built_wheel() {
    find "${ROOT_DIR}/dist" -maxdepth 1 -name "cutelingoexpress-*.whl" -print -quit
}

install_built_wheel() {
    local wheel_path="$1"

    if [[ -z "${wheel_path}" || ! -f "${wheel_path}" ]]; then
        error "Built wheel was not found in ${ROOT_DIR}/dist."
        return 1
    fi

    log "Installing built wheel: ${wheel_path}"
    "${PYTHON}" -m pip install --force-reinstall --no-deps "${wheel_path}"
}

verify_package_import() {
    log "Verifying installed package import and version."
    local import_output

    import_output="$(
        cd "${ROOT_DIR}/dist"
        "${PYTHON}" -c "import version; print(f'Package import ok: {version.VERSION}')"
    )"
    printf '%s\n' "${import_output}"
    IMPORT_DETAILS="${import_output#Package import ok: }"
}

main() {
    local wheel_path=""
    local exit_code=1

    parse_arguments "$@"

    if prepare_virtual_environment; then
        VENV_OK=1
        mark_result "Virtualenv" "PASS" ".venv is available"
    else
        mark_result "Virtualenv" "FAIL" "Could not create or reuse .venv"
    fi

    if [[ "${VENV_OK}" -eq 1 ]]; then
        if install_development_dependencies; then
            INSTALL_OK=1
            mark_result "Dependencies" "PASS" "Editable install with dev dependencies completed"
        else
            mark_result "Dependencies" "FAIL" "Dependency installation failed"
        fi
    else
        mark_result "Dependencies" "SKIP" "Skipped because .venv is unavailable"
    fi

    if [[ "${INSTALL_OK}" -eq 1 ]]; then
        if verify_runtime_version; then
            VERSION_OK=1
            mark_result "Version" "PASS" "auto_trans.py --version completed"
        else
            mark_result "Version" "FAIL" "Unexpected version command output"
        fi

        if run_pylint; then
            PYLINT_OK=1
            mark_result "Pylint" "PASS" "${PYLINT_DETAILS}"
        else
            mark_result "Pylint" "FAIL" "${PYLINT_DETAILS}"
        fi

        if run_tests_with_coverage; then
            TESTS_OK=1
            mark_result "Tests+Coverage" "PASS" "${TESTS_DETAILS}"
        else
            mark_result "Tests+Coverage" "FAIL" "${TESTS_DETAILS}"
        fi
    else
        mark_result "Version" "SKIP" "Skipped because dependencies are unavailable"
        mark_result "Pylint" "SKIP" "Skipped because dependencies are unavailable"
        mark_result "Tests+Coverage" "SKIP" "Skipped because dependencies are unavailable"
    fi

    if [[ "${VERSION_OK}" -eq 1 && "${PYLINT_OK}" -eq 1 && "${TESTS_OK}" -eq 1 ]]; then
        if clean_package_artifacts; then
            CLEAN_OK=1
            mark_result "Clean Build" "PASS" "Stale package artifacts removed"
        else
            mark_result "Clean Build" "FAIL" "Could not remove stale package artifacts"
        fi
    else
        mark_result "Clean Build" "SKIP" "Skipped because a quality gate failed"
    fi

    if [[ "${CLEAN_OK}" -eq 1 ]]; then
        if build_package; then
            BUILD_OK=1
            mark_result "Package Build" "PASS" "${BUILD_DETAILS}"
        else
            mark_result "Package Build" "FAIL" "${BUILD_DETAILS}"
        fi
    else
        mark_result "Package Build" "SKIP" "Skipped because clean step failed"
    fi

    if [[ "${BUILD_OK}" -eq 1 ]]; then
        wheel_path="$(find_built_wheel)"
        if [[ -n "${wheel_path}" ]]; then
            WHEEL_OK=1
            WHEEL_DETAILS="$(basename "${wheel_path}")"
            mark_result "Wheel" "PASS" "${WHEEL_DETAILS}"
        else
            mark_result "Wheel" "FAIL" "No wheel was found in dist/"
        fi
    else
        mark_result "Wheel" "SKIP" "Skipped because package build failed"
    fi

    if [[ "${WHEEL_OK}" -eq 1 ]]; then
        if install_built_wheel "${wheel_path}"; then
            PACKAGE_INSTALL_OK=1
            mark_result "Wheel Install" "PASS" "Built wheel installed into .venv"
        else
            mark_result "Wheel Install" "FAIL" "Built wheel installation failed"
        fi
    else
        mark_result "Wheel Install" "SKIP" "Skipped because no wheel is available"
    fi

    if [[ "${PACKAGE_INSTALL_OK}" -eq 1 ]]; then
        if verify_package_import; then
            IMPORT_OK=1
            mark_result "Import Check" "PASS" "${IMPORT_DETAILS}"
        else
            mark_result "Import Check" "FAIL" "Installed package import failed"
        fi
    else
        mark_result "Import Check" "SKIP" "Skipped because wheel install failed"
    fi

    if [[ "${VENV_OK}" -eq 1 && "${INSTALL_OK}" -eq 1 && "${VERSION_OK}" -eq 1 && "${PYLINT_OK}" -eq 1 && "${TESTS_OK}" -eq 1 && "${CLEAN_OK}" -eq 1 && "${BUILD_OK}" -eq 1 && "${WHEEL_OK}" -eq 1 && "${PACKAGE_INSTALL_OK}" -eq 1 && "${IMPORT_OK}" -eq 1 ]]; then
        exit_code=0
    fi

    if [[ "${exit_code}" -eq 0 ]]; then
        log "localPipeline.sh completed successfully"
    else
        error "localPipeline.sh completed with failing mandatory stage(s)"
    fi
    print_summary
    exit "${exit_code}"
}

main "$@"
