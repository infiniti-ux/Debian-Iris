#!/bin/bash
# =============================================================================
# scripts/uninstall.sh — remove what scripts/install.sh put on the system
#
#   sudo scripts/uninstall.sh [--restore-settings] [--dry-run] [--yes]
#
# How it decides what to delete:
#   It replays /var/lib/iris/manifest — the log install.sh wrote as it went — and
#   only removes paths inside the allowlist in scripts/lib/common.sh. It does not
#   `rm -rf /usr/share/themes/*`, does not guess, and will not touch the theme
#   tree unless the .iris-owned marker file is present (so a third-party or
#   hand-made theme called "Iris" is never deleted).
#
# Anything that was overwritten is restored from /var/lib/iris/backup.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/common.sh
. "${SCRIPT_DIR}/lib/common.sh"

RESTORE_SETTINGS=0
TARGET_USER="${SUDO_USER:-$(id -un)}"

while [ $# -gt 0 ]; do
    case "$1" in
        --restore-settings) RESTORE_SETTINGS=1; shift ;;
        --dry-run|-n)       DRY_RUN=1; shift ;;
        --yes|-y)           ASSUME_YES=1; shift ;;
        -h|--help)          sed -n '3,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)                  die "unknown argument: $1 (try --help)" ;;
    esac
done

need_root
removed=0 restored=0 skipped=0

step "About to remove"
if [ -f "$IRIS_MANIFEST" ]; then
    sed 's/^/      /' "$IRIS_MANIFEST"
    printf '    (%s entries from %s)\n' "$(wc -l <"$IRIS_MANIFEST")" "$IRIS_MANIFEST"
else
    warn "no manifest at $IRIS_MANIFEST — falling back to the known-good path list."
    warn "Only files matching Iris' own names will be removed."
fi

if ! is_dry; then
    confirm "Remove the above from the system?" || die "cancelled"
fi

# --- 1. restore overwritten files --------------------------------------------
if [ -d "$IRIS_BACKUP_DIR" ]; then
    step "Restoring overwritten files"
    while IFS= read -r orig; do
        [ -n "$orig" ] || continue
        name="$(printf '%s' "${orig#/}" | tr '/' '+')"
        copy="${IRIS_BACKUP_DIR}/${name}"
        [ -e "$copy" ] || continue
        path_is_allowed "$copy" || copy="${IRIS_BACKUP_DIR}/${name}"
        run cp -a "$copy" "$orig" && { log "restored $orig"; restored=$((restored + 1)); }
        # a directory we replaced wholesale: restore, then drop the stash copy
        case "$copy" in
            "${IRIS_BACKUP_DIR}"/*) run rm -rf -- "$copy" ;;
            *) warn "not deleting unexpected backup path: $copy" ;;
        esac
    done < <(awk -F'\t' '$1=="backup"{print $2}' "$IRIS_MANIFEST" 2>/dev/null || true)
fi

# --- 2. remove manifest entries (reverse order: children before parents) -----
#
# The theme tree is handled first-and-atomically: /usr/share/themes/Iris is only
# deleted if our ownership marker is there. The marker itself is deliberately
# NOT deleted as a separate manifest entry, otherwise the check below would see
# a tree without a marker and refuse to clean it up.
step "Removing installed files"
THEME_TREE="/usr/share/themes/Iris"
theme_owned=0
[ -f "${THEME_TREE}/.iris-owned" ] && theme_owned=1

if [ -f "$IRIS_MANIFEST" ]; then
    while IFS=$'\t' read -r kind path; do
        [ -n "${path:-}" ] || continue
        case "$path" in
            "${THEME_TREE}"|"${THEME_TREE}"/*) continue ;;   # handled below
        esac
        case "$kind" in
            file|dir)
                if remove_path "$path"; then
                    removed=$((removed + 1))
                    prune_iris_dirs "$path"
                fi ;;
            tree)
                warn "manifest tree entry $path — refusing to delete trees not owned via the marker" ;;
            *)
                warn "manifest: unknown entry kind '$kind' for $path — ignored" ;;
        esac
    done < <(tac "$IRIS_MANIFEST")
else
    warn "no manifest: using the known Iris path list instead."
    for p in /usr/share/xsessions/iris.desktop \
             /usr/share/wayland-sessions/iris-wayland.desktop \
             /usr/share/cinnamon-session/sessions/iris.session \
             /usr/share/cinnamon-session/sessions/iris-wayland.session \
             /usr/share/backgrounds/iris-aluminium-dark.png \
             /usr/share/iris/iris.gsettings \
             /etc/lightdm/lightdm.conf.d/60-iris.conf; do
        [ -e "$p" ] || continue
        remove_path "$p" && removed=$((removed + 1))
        prune_iris_dirs "$p"
    done
    [ -f "${THEME_TREE}/.iris-owned" ] && theme_owned=1
fi

if [ "$theme_owned" = 1 ]; then
    remove_tree_owned "$THEME_TREE" && removed=$((removed + 1)) && log "removed $THEME_TREE"
elif [ -d "$THEME_TREE" ]; then
    warn "left $THEME_TREE in place: no .iris-owned marker, so it may not be ours."
fi

# --- 3. optional: put the pre-Iris gsettings back -----------------------------
if [ "$RESTORE_SETTINGS" = 1 ]; then
    step "Restoring pre-Iris gsettings for ${TARGET_USER}"
    home="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
    newest=""
    for d in "${IRIS_STATE_DIR}/settings-backup" "${home}/.local/share/iris/settings-backup"; do
        [ -d "$d" ] || continue
        cand="$(find "$d" -maxdepth 1 -name '*.gsettings' -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)"
        [ -n "$cand" ] && newest="$cand"
    done
    if [ -z "$newest" ]; then
        warn "no settings backup found — leaving gsettings untouched."
    else
        log "using $newest"
        run bash "${SCRIPT_DIR}/apply-settings.sh" --user "$TARGET_USER" --restore "$newest" || \
            warn "restore did not complete; the file is still at $newest"
    fi
fi

# --- 4. tidy state ------------------------------------------------------------
step "Cleaning state"
if ! is_dry; then
    [ -f "$IRIS_MANIFEST" ] && rm -f "$IRIS_MANIFEST"
    [ -d "$IRIS_BACKUP_DIR" ] && [ -z "$(ls -A "$IRIS_BACKUP_DIR" 2>/dev/null)" ] && rmdir "$IRIS_BACKUP_DIR"
fi

log "removed=${removed} restored=${restored} skipped=${skipped}"
cat <<'EOF'

    Iris files are gone. The Cinnamon desktop itself is untouched — packages
    installed with --packages are kept (removing packages is a system-wide
    operation and is left as a deliberate, manual step):

      sudo apt-get remove --auto-remove cinnamon-core lightdm

    Log out and back in (or restart the display manager) to clear a cached theme.
EOF
