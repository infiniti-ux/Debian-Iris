#!/bin/bash
# =============================================================================
# scripts/lib/common.sh — shared helpers for the Iris installers
#
# Design rules (these exist because a previous revision of this repo shipped a
# destructive installer; see docs/SAFETY.md):
#   1. Never modify a config file in place. Install a drop-in, or back the file
#      up first and record it in the manifest.
#   2. Every path we create is written to a manifest; uninstall removes ONLY
#      manifest entries, and only under an explicit allowlist of prefixes.
#   3. Never `rm -rf` a path built from variables without that allowlist check.
#   4. Never run apt / touch the display manager without the operator opting in.
#   5. Everything supports --dry-run.
# =============================================================================

IRIS_STATE_DIR="/var/lib/iris"
IRIS_MANIFEST="${IRIS_STATE_DIR}/manifest"
IRIS_BACKUP_DIR="${IRIS_STATE_DIR}/backup"

# Paths this tool is allowed to create and later remove. Anything outside these
# prefixes is refused, which is what keeps `uninstall` from deleting a user's
# real theme or /etc config.
IRIS_ALLOWED_PREFIXES=(
    "/usr/share/themes/Iris"
    "/usr/share/backgrounds"
    "/usr/share/xsessions/iris.desktop"
    "/usr/share/wayland-sessions/iris-wayland.desktop"
    "/usr/share/cinnamon-session/sessions"
    "/etc/lightdm/lightdm.conf.d"
    "/etc/iris"
    "/usr/share/iris"
    "/var/lib/iris"
)

DRY_RUN="${IRIS_DRY_RUN:-0}"
ASSUME_YES="${IRIS_YES:-0}"

_iris_color() { [ -t 2 ] && printf '\033[%sm' "$1" || printf ''; }

log()  { printf '%s[ iris ]%s %s\n'        "$(_iris_color '1;34')" "$(_iris_color 0)" "$*"; }
warn() { printf '%s[ warn ]%s %s\n'        "$(_iris_color '1;33')" "$(_iris_color 0)" "$*" >&2; }
err()  { printf '%s[ fail ]%s %s\n'        "$(_iris_color '1;31')" "$(_iris_color 0)" "$*" >&2; }
die()  { err "$*"; exit 1; }

step() { printf '\n%s==> %s%s\n' "$(_iris_color '1;36')" "$*" "$(_iris_color 0)"; }

is_dry() { [ "${DRY_RUN}" = "1" ]; }

# run <cmd...> — execute unless --dry-run was given
run() {
    if is_dry; then
        printf '    [dry-run] %s\n' "$*"
        return 0
    fi
    "$@"
}

need_root() {
    [ "$(id -u)" -eq 0 ] || die "this must run as root (try: sudo $0)"
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

repo_root() {
    (cd "$(dirname "$(readlink -f "${BASH_SOURCE[1]:-$0}")")/.." && pwd)
}

confirm() {
    local prompt="${1:-Continue?}"
    [ "${ASSUME_YES}" = "1" ] && return 0
    if [ ! -t 0 ]; then
        err "not a terminal: refusing to ask. Re-run with --yes if you really mean it."
        return 1
    fi
    printf '%s (y/N) ' "$prompt"
    local reply
    read -r reply
    case "$reply" in
        [yY]|[yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

path_is_allowed() {
    local p="$1" prefix
    for prefix in "${IRIS_ALLOWED_PREFIXES[@]}"; do
        case "$p" in
            "$prefix"|"$prefix"/*) return 0 ;;
        esac
    done
    return 1
}

_manifest_add() { # <kind> <path>
    local kind="$1" p="$2"
    [ -d "$IRIS_STATE_DIR" ] || run mkdir -p "$IRIS_STATE_DIR" || return 1
    is_dry && { printf '    [dry-run] manifest += %s\t%s\n' "$kind" "$p"; return 0; }
    # keep it unique
    if [ -f "$IRIS_MANIFEST" ] && grep -qF "	$p" "$IRIS_MANIFEST" 2>/dev/null; then
        grep -q "^$kind	$p$" "$IRIS_MANIFEST" && return 0
    fi
    printf '%s\t%s\n' "$kind" "$p" >>"$IRIS_MANIFEST"
}

backup_path() { # <path> — copies an existing file aside, idempotently
    local p="$1" name dest
    [ -e "$p" ] || return 0
    name="$(printf '%s' "${p#/}" | tr '/' '+')"
    dest="${IRIS_BACKUP_DIR}/${name}"
    [ -d "$IRIS_BACKUP_DIR" ] || run mkdir -p "$IRIS_BACKUP_DIR" || return 1
    if [ -e "$dest" ]; then
        return 0   # first backup wins; never overwrite a pristine copy
    fi
    run cp -a "$p" "$dest" || return 1
    _manifest_add backup "$p"
}

remove_path() { # <path> — only inside the allowlist; dirs are removed if empty
    local p="$1"
    [ -n "$p" ] || return 0
    if ! path_is_allowed "$p"; then
        warn "refusing to remove '$p' (outside the Iris allowlist)"
        return 1
    fi
    if [ -d "$p" ] && [ ! -L "$p" ]; then
        run find "$p" -mindepth 1 -maxdepth 1 -print -quit | grep -q . && {
            warn "keeping non-empty directory $p"
            return 0
        }
        run rmdir "$p"
        return 0
    fi
    run rm -f "$p"
}

# Remove a directory tree that Iris owns outright. The allowlist is checked
# twice on purpose: once for the prefix, once against an exact set of owned
# trees. Anything else falls back to "rmdir if empty", never rm -rf.
remove_tree_owned() { # <dir>
    local p="$1"
    path_is_allowed "$p" || { warn "refusing to remove '$p' (outside the Iris allowlist)"; return 1; }
    [ -d "$p" ] || return 0
    case "$p" in
        "/usr/share/themes/Iris"|"/usr/share/themes/Iris"/*)
            run rm -rf -- "$p"
            return 0 ;;
    esac
    if ! run rmdir "$p" 2>/dev/null; then
        warn "keeping non-empty directory $p (not an Iris-owned tree)"
    fi
    return 0
}

install_file() { # <src> <dest> <mode>
    local src="$1" dest="$2" mode="${3:-0644}"
    [ -f "$src" ] || { err "missing source file: $src"; return 1; }
    backup_path "$dest"
    run install -D -m "$mode" "$src" "$dest" || return 1
    _manifest_add file "$dest"
}

install_tree() { # <srcdir> <destdir>
    local src="$1" dest="$2"
    [ -d "$src" ] || { err "missing source dir: $src"; return 1; }
    backup_path "$dest"
    run mkdir -p "$dest" || return 1
    run cp -aR "${src}/." "$dest/" || return 1
    _manifest_add tree "$dest"
}

# Directories Iris may have created itself. Only these are pruned when empty —
# /usr/share/backgrounds, /usr/share/xsessions etc. belong to other packages and
# must survive even when they end up empty.
IRIS_OWNED_DIRS=(
    "/usr/share/iris"
    "/usr/share/cinnamon-session/sessions"
    "/etc/lightdm/lightdm.conf.d"
)

prune_iris_dirs() { # <path we just removed> — walk up, rmdir empty Iris-owned dirs
    local p parent
    p="$(dirname "$1")"
    for parent in "$p" "$(dirname "$p")"; do
        case " ${IRIS_OWNED_DIRS[*]} " in
            *" $parent "*)
                [ -d "$parent" ] || continue
                [ -z "$(ls -A "$parent" 2>/dev/null)" ] && run rmdir "$parent"
                ;;
        esac
    done
}

# --- environment probes -------------------------------------------------------

os_id() { . /etc/os-release 2>/dev/null && printf '%s' "${ID:-unknown}"; }
os_version_id() { . /etc/os-release 2>/dev/null && printf '%s' "${VERSION_ID:-0}"; }

is_debianish() {
    local id
    id="$(os_id)"
    case "$id" in
        debian|linuxmint|ubuntu|devuan|element|peppermint) return 0 ;;
    esac
    . /etc/os-release 2>/dev/null
    case "${ID_LIKE:-}" in
        *debian*|*ubuntu*) return 0 ;;
    esac
    return 1
}

# A graphical session is active if someone is logged into a seat.
graphical_session_active() {
    have_cmd loginctl || return 1
    loginctl list-sessions --no-legend 2>/dev/null | awk '$3!="" {print $3}' | grep -qv '^$'
}

# Prints the name of the enabled display manager, if any.
display_manager_enabled() {
    local dm
    for dm in gdm3 gdm lightdm lxdm sddm greetd; do
        if systemctl is-enabled --quiet "${dm}.service" 2>/dev/null; then
            printf '%s' "$dm"
            return 0
        fi
    done
    return 1
}

# Which session (if any) the target user is currently running — used to decide
# whether applying settings is safe.
user_has_live_session() { # <username>
    local u="$1"
    [ "$u" = "$(id -un)" ] && [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ] && return 0
    have_cmd loginctl || return 1
    loginctl list-sessions --no-legend 2>/dev/null | awk -v u="$u" '$2==u{found=1} END{exit !found}'
}

# --- run something as the target user, inside their session bus -------------
# usage: as_user <user> <cmd> [args...]
as_user() {
    local user="$1"; shift
    local uid runtime
    uid="$(id -u "$user" 2>/dev/null)" || { err "no such user: $user"; return 1; }
    runtime="/run/user/${uid}"
    local env=(
        "HOME=$(getent passwd "$user" | cut -d: -f6)"
        "USER=$user" "LOGNAME=$user"
        "XDG_RUNTIME_DIR=$runtime"
        "DBUS_SESSION_BUS_ADDRESS=unix:path=${runtime}/bus"
        "PATH=$PATH"
    )
    if [ "$(id -u)" -eq 0 ]; then
        env -i "${env[@]}" runuser -u "$user" -- "$@"
    else
        "$@"
    fi
}

gsettings_live_bus() { # <user> — succeeds if the user's session bus is reachable
    local user="$1" uid
    uid="$(id -u "$user" 2>/dev/null)" || return 1
    [ -S "/run/user/${uid}/bus" ]
}
