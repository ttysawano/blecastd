#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail

APP_NAME="blecastd"
INSTALL_DIR="/opt/blecastd"
CONFIG_DIR="/etc/blecastd"
CONFIG_FILE="${CONFIG_DIR}/blecastd.toml"
CONFIG_EXAMPLE="${CONFIG_DIR}/blecastd.toml.example"
SERVICE_FILE="/etc/systemd/system/blecastd.service"
TMPFILES_FILE="/etc/tmpfiles.d/blecastd.conf"
GROUP_NAME="blecast"

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        echo "install.sh must be run as root. Try: sudo ./install.sh" >&2
        exit 1
    fi
}

require_command() {
    local command_name="$1"
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "required command not found: ${command_name}" >&2
        exit 1
    fi
}

repo_root() {
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd
}

install_sources() {
    local src_root="$1"

    install -d -m 0755 "${INSTALL_DIR}"
    rm -rf "${INSTALL_DIR:?}/src" "${INSTALL_DIR:?}/examples" "${INSTALL_DIR:?}/etc"
    cp -a "${src_root}/src" "${INSTALL_DIR}/"
    cp -a "${src_root}/examples" "${INSTALL_DIR}/"
    cp -a "${src_root}/etc" "${INSTALL_DIR}/"
    install -m 0644 "${src_root}/README.adoc" "${INSTALL_DIR}/README.adoc"
    install -m 0644 "${src_root}/SPEC.adoc" "${INSTALL_DIR}/SPEC.adoc"
    install -m 0644 "${src_root}/pyproject.toml" "${INSTALL_DIR}/pyproject.toml"
    find "${INSTALL_DIR}" -type d -name "__pycache__" -prune -exec rm -rf {} +
    find "${INSTALL_DIR}" -type d -name ".pytest_cache" -prune -exec rm -rf {} +
    find "${INSTALL_DIR}" -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete
}

install_config() {
    local src_root="$1"

    install -d -m 0755 "${CONFIG_DIR}"
    install -m 0644 "${src_root}/etc/blecastd.toml" "${CONFIG_EXAMPLE}"
    if [[ ! -e "${CONFIG_FILE}" ]]; then
        install -m 0644 "${src_root}/etc/blecastd.toml" "${CONFIG_FILE}"
        echo "installed default configuration: ${CONFIG_FILE}"
    else
        echo "kept existing configuration: ${CONFIG_FILE}"
        echo "installed updated example: ${CONFIG_EXAMPLE}"
    fi
}

main() {
    require_root
    require_command cp
    require_command groupadd
    require_command getent
    require_command install
    require_command find
    require_command rm
    require_command systemctl
    require_command systemd-tmpfiles

    local src_root
    src_root="$(repo_root)"

    if ! getent group "${GROUP_NAME}" >/dev/null; then
        groupadd --system "${GROUP_NAME}"
        echo "created system group: ${GROUP_NAME}"
    fi

    install_sources "${src_root}"
    install_config "${src_root}"
    install -m 0644 "${src_root}/etc/blecastd.service" "${SERVICE_FILE}"
    install -m 0644 "${src_root}/etc/tmpfiles.d/blecastd.conf" "${TMPFILES_FILE}"

    systemd-tmpfiles --create "${TMPFILES_FILE}"
    systemctl daemon-reload
    systemctl enable "${APP_NAME}.service"
    systemctl start "${APP_NAME}.service"

    echo "installed and started ${APP_NAME}.service"
    echo "check logs with: journalctl -u ${APP_NAME} -f"
}

main "$@"
