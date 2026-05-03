#!/usr/bin/env bash
set -euo pipefail

TARGET="${TARGET:-/run/blecastd/dynamic_data.bin}"
DYNAMIC_DATA_LEN="${DYNAMIC_DATA_LEN:-22}"
INTERVAL_SEC="${INTERVAL_SEC:-2}"

# This writer produces only dynamic data. Do not include the static header here;
# blecastd prepends the configured static header to the user field.

write_dynamic_data_atomic_from_hex() {
    local hex="$1"
    local dir
    local tmp

    dir="$(dirname "$TARGET")"
    tmp="$(mktemp "${dir}/.dynamic_data.tmp.XXXXXX")"

    printf '%s' "$hex" | xxd -r -p > "$tmp"
    truncate -s "$DYNAMIC_DATA_LEN" "$tmp"
    chmod 0664 "$tmp"
    mv -f "$tmp" "$TARGET"
}

collect_dynamic_data_hex() {
    local timestamp
    local temp_x100
    local status

    timestamp="$(date +%s)"
    temp_x100=2345
    status=0

    printf '%08x%04x%02x' \
        "$timestamp" \
        "$temp_x100" \
        "$status"
}

main() {
    while true; do
        hex="$(collect_dynamic_data_hex)"
        write_dynamic_data_atomic_from_hex "$hex"
        sleep "$INTERVAL_SEC"
    done
}

main "$@"
