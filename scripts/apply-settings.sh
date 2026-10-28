#!/bin/bash
# =============================================================================
# scripts/apply-settings.sh — apply an Iris gsettings profile, safely
#
#   ./scripts/apply-settings.sh [profile] [--user NAME] [--dry-run]
#                               [--restore BACKUPFILE] [--yes]
#
# Why this exists instead of `dconf load`:
#   `dconf load /org/cinnamon/ < dump` writes whatever the file contains,
#   including keys that no longer exist, and it clobbers unrelated user choices
#   in the same subtree. Here every line is checked against the *installed*
#   GSettings schema before it is written, unknown keys are skipped loudly, and
#   the previous value of every key we touch is saved so it can be restored.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/common.sh
. "${SCRIPT_DIR}/lib/common.sh"

REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROFILE="${REPO_DIR}/config/gsettings/iris.gsettings"
TARGET_USER="${SUDO_USER:-$(id -un)}"
RESTORE_FILE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --user)    TARGET_USER="${2:?--user needs a name}"; shift 2 ;;
        --restore) RESTORE_FILE="${2:?--restore needs a backup file}"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        --yes|-y)  ASSUME_YES=1; shift ;;
        -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        --*)       die "unknown option: $1" ;;
        *)         PROFILE="$1"; shift ;;
    esac
done

if [ -n "$RESTORE_FILE" ]; then
    PROFILE="$RESTORE_FILE"
    [ -f "$PROFILE" ] || die "restore file not found: $PROFILE"
fi
[ -f "$PROFILE" ] || die "profile not found: $PROFILE"

# --- where do we write? -------------------------------------------------------
if [ "$(id -u)" -eq 0 ] && [ "$TARGET_USER" != "root" ]; then
    RUN_AS_USER=1
    gsettings_live_bus "$TARGET_USER" || die \
  "no D-Bus session bus for user '$TARGET_USER' (/run/user/$(id -u "$TARGET_USER")/bus missing).
   gsettings only works inside a running graphical session.
   Either run this from a terminal in that session, or install the .deb and let
   dconf defaults handle it at first login."
else
    RUN_AS_USER=0
    have_cmd gsettings || die "gsettings not installed (apt install dconf-cli)"
    [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ] || die "DBUS_SESSION_BUS_ADDRESS is empty — run this inside your desktop session."
fi

gs() { # gsettings wrapper bound to the right user
    if [ "$RUN_AS_USER" = "1" ]; then
        as_user "$TARGET_USER" gsettings "$@"
    else
        gsettings "$@"
    fi
}

# --- cache of what actually exists on this machine ----------------------------
VALID_SCHEMA_LIST="$(gs list-schemas 2>/dev/null | tr '\n' ' ')"
key_cache_file="$(mktemp)"
trap 'rm -f "$key_cache_file"' EXIT

schema_known() { [[ " $VALID_SCHEMA_LIST " == *" $1 "* ]]; }

keys_of() { # <schema> — cached
    local schema="$1" line
    if line="$(grep -m1 "^${schema}	" "$key_cache_file" 2>/dev/null || true)"; then
        [ -n "$line" ] && { printf '%s' "${line#*	}"; return 0; }
    fi
    local keys
    keys="$(gs list-keys "$schema" 2>/dev/null | tr '\n' ' ' || true)"
    printf '%s\t%s\n' "$schema" "$keys" >>"$key_cache_file"
    printf '%s' "$keys"
}

# --- backup file --------------------------------------------------------------
BACKUP_DIR="${IRIS_STATE_DIR}/settings-backup"
if [ "$(id -u)" -ne 0 ]; then
    BACKUP_DIR="${HOME}/.local/share/iris/settings-backup"
fi
if [ -z "$RESTORE_FILE" ]; then
    BACKUP_FILE="${BACKUP_DIR}/$(date -u +%Y%m%dT%H%M%SZ)-pre-iris.gsettings"
    is_dry || { mkdir -p "$BACKUP_DIR"; : >"$BACKUP_FILE"; }
else
    BACKUP_FILE=""   # restoring: no need to back up again
fi

applied=0 equal=0 unknown=0 failed=0
declare -a unknown_list=()

step "Applying Iris settings profile"
printf '    profile : %s\n' "$PROFILE"
printf '    as user : %s\n' "$TARGET_USER"
[ -n "$BACKUP_FILE" ] && printf '    backup  : %s\n' "$BACKUP_FILE"
echo

# --- main loop ----------------------------------------------------------------
lineno=0
while IFS= read -r raw || [ -n "$raw" ]; do
    lineno=$((lineno + 1))
    # comment / blank lines: only recognise '#' at the start of the line, so that
    # colour values like '#eef0f3' survive.
    local_trimmed="${raw#"${raw%%[![:space:]]*}"}"
    [ -n "$local_trimmed" ] || continue
    case "$local_trimmed" in \#*) continue ;; esac
    line="$raw"
    case "$line" in
        *$'\t'*) : ;;
        *) warn "line $lineno: not tab-separated, skipped"; continue ;;
    esac

    IFS=$'\t' read -r schema key value <<<"$line"
    [ -n "${schema:-}" ] && [ -n "${key:-}" ] || continue
    schema="${schema//[[:space:]]/}"; key="${key//[[:space:]]/}"
    value="${value#"${value%%[![:space:]]*}"}"   # trim leading space
    if [ -z "$value" ]; then
        if [ -n "$RESTORE_FILE" ]; then
            warn "line $lineno: ${schema} ${key} had no previous value (was unset) — left as-is"
        else
            warn "line $lineno: empty value for ${schema} ${key}"
        fi
        continue
    fi

    if ! schema_known "$schema"; then
        warn "unknown schema: $schema (line $lineno) — skipped"
        unknown=$((unknown + 1)); unknown_list+=("$schema.$key [no schema]")
        continue
    fi
    if [[ " $(keys_of "$schema") " != *" $key "* ]]; then
        warn "key not in this Cinnamon version: ${schema} ${key} — skipped"
        unknown=$((unknown + 1)); unknown_list+=("${schema} ${key} [no key]")
        continue
    fi

    current="$(gs get "$schema" "$key" 2>/dev/null || true)"
    if [ "$current" = "$value" ]; then
        equal=$((equal + 1))
        continue
    fi

    if is_dry; then
        printf '    [dry-run] %s %s : %s  ->  %s\n' "$schema" "$key" "${current:-?}" "$value"
        applied=$((applied + 1))
        continue
    fi

    # Record the old value so --restore can put it back. A key that was unset
    # (gsettings get failed) has no restorable value, so it is left out rather
    # than written as an empty string, which would fail on restore.
    if [ -n "$BACKUP_FILE" ] && [ -n "$current" ]; then
        printf '%s\t%s\t%s\n' "$schema" "$key" "$current" >>"$BACKUP_FILE"
    fi

    if gs set "$schema" "$key" "$value" 2>/dev/null; then
        printf '    set  %s %s = %s\n' "$schema" "$key" "$value"
        applied=$((applied + 1))
    else
        err "gsettings set failed: ${schema} ${key} = ${value}"
        failed=$((failed + 1))
    fi
done <"$PROFILE"

echo
log "applied=${applied} unchanged=${equal} skipped-unknown=${unknown} failed=${failed}"
if [ ${#unknown_list[@]} -gt 0 ]; then
    printf '    (skipped because the installed Cinnamon does not define them:\n'
    printf '       %s)\n' "$(printf '%s, ' "${unknown_list[@]}" | sed 's/, $//')"
fi
[ "$failed" -eq 0 ] || exit 1
exit 0
