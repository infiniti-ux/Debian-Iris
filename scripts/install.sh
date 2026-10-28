#!/bin/bash
# =============================================================================
# scripts/install.sh — install the Iris desktop skin on Debian 13+
#
# Default action (safe): copy theme + wallpaper into place. Nothing else.
# Everything that can affect a running system is opt-in:
#
#   --packages         apt-get install the Cinnamon/lightdm stack first
#   --with-session     register "Iris" in the login screen (xsessions)
#   --with-lightdm     make Iris the default session in a LightDM DROP-IN file
#   --apply-settings   write the Iris gsettings profile for the console user
#   --all              the three above together (convenience for a fresh box)
#
#   --dry-run          print what would happen
#   --yes              no prompts
#   --force            skip the "don't do this inside a live session" guard
#
# What this script will never do:
#   - overwrite /etc/lightdm/lightdm.conf (it uses /etc/lightdm/lightdm.conf.d/)
#   - enable/disable/switch the display manager or run systemctl
#   - write dconf keys that the installed Cinnamon does not define
#   - install a plymouth theme (a bad boot splash is a hard failure to recover)
#   - remove anything (see scripts/uninstall.sh + the manifest it maintains)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/common.sh
. "${SCRIPT_DIR}/lib/common.sh"

REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

WITH_PACKAGES=0
WITH_SESSION=0
WITH_LIGHTDM=0
WITH_SETTINGS=0

usage() { sed -n '3,26p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case "$1" in
        --packages)      WITH_PACKAGES=1; shift ;;
        --with-session)  WITH_SESSION=1; shift ;;
        --with-lightdm)  WITH_LIGHTDM=1; WITH_SESSION=1; shift ;;
        --apply-settings) WITH_SETTINGS=1; shift ;;
        --all)           WITH_PACKAGES=1; WITH_SESSION=1; WITH_LIGHTDM=1; WITH_SETTINGS=1; shift ;;
        --dry-run|-n)    DRY_RUN=1; shift ;;
        --yes|-y)        ASSUME_YES=1; shift ;;
        --force)         FORCE=1; shift ;;
        -h|--help)       usage; exit 0 ;;
        *)               die "unknown argument: $1 (try --help)" ;;
    esac
done
FORCE="${FORCE:-0}"

TARGET_USER="${SUDO_USER:-$(id -un)}"
USER_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

need_root

step "Preflight"
# 1. OS check — this repo targets Debian's package set.
if ! is_debianish; then
    warn "this system is not Debian/Ubuntu-family ('"$(os_id)"'); the package names here will not resolve."
    [ "$FORCE" = 1 ] || die "aborting (use --force to continue anyway)"
fi
if [ "$(os_id)" = "debian" ] && [ "$(os_version_id)" -lt 13 ] 2>/dev/null; then
    warn "Debian $(os_version_id) detected: Iris targets Debian 13 (trixie) and Cinnamon 6.4+."
    [ "$FORCE" = 1 ] || die "aborting (use --force to continue anyway)"
fi
printf '    os        : %s %s\n' "$(os_id)" "$(os_version_id)"
printf '    user      : %s\n' "$TARGET_USER"
printf '    mode      : %s\n' "$(is_dry && echo 'DRY-RUN (nothing will be written)' || echo 'apply')"

# 2. Warn if a desktop is live: replacing the DE while logged in is what causes
#    the classic blank-screen. Installing *theme files* is fine either way.
if [ "$WITH_PACKAGES" = 1 ] && graphical_session_active && [ "$FORCE" != 1 ]; then
    err "a graphical session is currently running. Installing/removing DE packages while logged in can"
    err "leave you with a broken greeter. Log out, switch to a text console (Ctrl+Alt+F3), run this"
    err "there — or pass --force if you accept the risk."
    exit 1
fi

plan=("theme -> /usr/share/themes/Iris" "wallpaper -> /usr/share/backgrounds/iris-aluminium.png")
[ "$WITH_SESSION" = 1 ]  && plan+=("sessions -> xsessions/iris.desktop, wayland-sessions/iris-wayland.desktop, cinnamon-session/sessions/iris*.session")
[ "$WITH_LIGHTDM" = 1 ]  && plan+=("lightdm drop-in -> /etc/lightdm/lightdm.conf.d/60-iris.conf")
[ "$WITH_SETTINGS" = 1 ] && plan+=("gsettings profile for $TARGET_USER")
[ "$WITH_PACKAGES" = 1 ] && plan+=("apt-get install the core package list")
printf '    plan:\n'; printf '      - %s\n' "${plan[@]}"

if ! is_dry; then
    confirm "Apply this plan to the system?" || die "cancelled by user"
fi

# ---------------------------------------------------------------------------
if [ "$WITH_PACKAGES" = 1 ]; then
    step "Installing core packages"
    have_cmd apt-get || die "apt-get not found; drop --packages and copy files only"
    PKGS=()
    while IFS= read -r l; do
        l="${l%%#*}"; l="${l//[[:space:]]/}"
        [ -n "$l" ] && PKGS+=("$l")
    done < "${REPO_DIR}/config/package-lists/iris-core.list.chroot"
    printf '    %s\n' "${PKGS[*]}"
    run env DEBIAN_FRONTEND=noninteractive apt-get update -qq
    run env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${PKGS[@]}"
    log "packages installed"
fi

step "Installing theme"
install_tree "${REPO_DIR}/theme/Iris" "/usr/share/themes/Iris"
# Ownership marker: uninstall.sh will only ever delete the installed tree if this
# file exists, so a hand-made theme that happens to be called "Iris" survives.
if is_dry; then
    printf '    [dry-run] write marker /usr/share/themes/Iris/.iris-owned\n'
else
    printf 'installed-by=%s\nrepo=%s\ndate=%s\n' "Debian-Iris/scripts/install.sh" "$REPO_DIR" "$(date -Is)" \
        > "/usr/share/themes/Iris/.iris-owned" || warn "could not write ownership marker"
    _manifest_add file "/usr/share/themes/Iris/.iris-owned"
fi
# Cinnamon looks up shell themes by directory name; make sure the metatheme
# file is where index.theme says it is.
[ -f "/usr/share/themes/Iris/index.theme" ] || is_dry || die "index.theme missing from installed tree"
log "theme installed at /usr/share/themes/Iris"

step "Installing wallpaper"
install_file "${REPO_DIR}/wallpapers/iris-aluminium.png" "/usr/share/backgrounds/iris-aluminium.png" 0644
install_file "${REPO_DIR}/config/gsettings/iris.gsettings" "/usr/share/iris/iris.gsettings" 0644

if [ "$WITH_SESSION" = 1 ]; then
    step "Registering the Iris session"
    for f in iris.session iris-wayland.session; do
        install_file "${REPO_DIR}/sessions/${f}" "/usr/share/cinnamon-session/sessions/${f}" 0644
    done
    install_file "${REPO_DIR}/sessions/iris.desktop" "/usr/share/xsessions/iris.desktop" 0644
    install_file "${REPO_DIR}/sessions/iris-wayland.desktop" "/usr/share/wayland-sessions/iris-wayland.desktop" 0644
    warn "the Wayland session needs the xwayland package or the desktop comes up black (Debian #1147594)."
    if [ "$WITH_PACKAGES" != 1 ]; then
        warn "you did not pass --packages: verify 'xwayland' is installed before using the Wayland entry."
    fi
    log "session registered — pick 'Iris' at the login screen"
fi

if [ "$WITH_LIGHTDM" = 1 ]; then
    step "Configuring LightDM default session (drop-in)"
    DM="$(display_manager_enabled || true)"
    if [ -n "$DM" ] && [ "$DM" != "lightdm" ] && [ "$FORCE" != 1 ]; then
        die "'${DM}' is the enabled display manager, not lightdm. Iris will not reconfigure it.
     Re-run with --with-lightdm --force to write the drop-in anyway (it will be ignored
     by ${DM}), or enable the Iris session in ${DM}'s own configuration."
    fi
    mkdir -p /etc/lightdm/lightdm.conf.d
    cat > /etc/lightdm/lightdm.conf.d/60-iris.conf <<'EOF'
# Iris — default session selection.
# Written by scripts/install.sh; scripts/uninstall.sh removes it.
# /etc/lightdm/lightdm.conf itself is never touched.
[Seat:*]
user-session=iris
EOF
    chmod 0644 /etc/lightdm/lightdm.conf.d/60-iris.conf
    _manifest_add file "/etc/lightdm/lightdm.conf.d/60-iris.conf"
    log "drop-in written (no changes to /etc/lightdm/lightdm.conf)"
fi

if [ "$WITH_SETTINGS" = 1 ]; then
    step "Applying gsettings profile for ${TARGET_USER}"
    if [ "$TARGET_USER" = "root" ]; then
        warn "target user is root — skipping; run scripts/apply-settings.sh from your own session instead."
    elif ! run bash "${SCRIPT_DIR}/apply-settings.sh" "${REPO_DIR}/config/gsettings/iris.gsettings" --user "$TARGET_USER" $(is_dry && echo --dry-run); then
        warn "could not apply settings (no live session bus?). Not fatal — start the session once, then run:"
        warn "  scripts/apply-settings.sh"
    fi
fi

step "Done"
{
    echo "  Theme files : /usr/share/themes/Iris"
    echo "  Manifest    : ${IRIS_MANIFEST}  (used by scripts/uninstall.sh)"
    echo
    echo "  Next steps:"
    if [ "$WITH_SESSION" = 1 ]; then
        echo "   1. Log out and choose 'Iris' at the login screen."
    else
        echo "   1. In the running session:  sudo -u ${TARGET_USER} ${SCRIPT_DIR}/apply-settings.sh"
        echo "      or point cinnamon-settings at the 'Iris' theme."
    fi
    echo "   2. Optional glassmorphism on app windows:"
    echo "      ~/.config/gtk-3.0/gtk.css  ->  @import url(\"/usr/share/themes/Iris/gtk-3.0/gtk-translucent.css\");"
    echo "   3. To undo everything:  sudo ${SCRIPT_DIR}/uninstall.sh"
} | sed 's/^/    /'
