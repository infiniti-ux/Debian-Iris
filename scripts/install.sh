#!/bin/bash
# =============================================================================
# scripts/install.sh — Debian Iris Desktop Environment Installer
# Base: Debian 13 (trixie) + Cinnamon Core + Aluminium OS inspired UI
# Usage: sudo ./scripts/install.sh
# =============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_HOME="$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)"
TARGET_USER="${SUDO_USER:-$USER}"

echo "[1/7] Memperbarui daftar paket..."
apt-get update

echo "[2/7] Menginstal dependensi inti (Cinnamon, LightDM, tema, dll)..."
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    cinnamon-core \
    cinnamon-l10n \
    lightdm \
    lightdm-gtk-greeter \
    xorg \
    xserver-xorg-video-all \
    xserver-xorg-input-all \
    papirus-icon-theme \
    bibata-cursor-theme \
    plymouth \
    plymouth-theme-iris \
    dconf-cli \
    gsettings-desktop-schemas \
    || true

echo "[3/7] Menyalin tema Iris ke /usr/share/themes..."
install -d -m 0755 /usr/share/themes/Iris
cp -a "${REPO_DIR}/theme/Iris/." /usr/share/themes/Iris/
chown -R root:root /usr/share/themes/Iris
chmod -R 0755 /usr/share/themes/Iris

echo "[4/7] Menyalin wallpaper ke /usr/share/backgrounds..."
install -d -m 0755 /usr/share/backgrounds
cp -a "${REPO_DIR}/wallpapers/iris-aluminium.png" /usr/share/backgrounds/iris-aluminium.png
chown root:root /usr/share/backgrounds/iris-aluminium.png
chmod 0644 /usr/share/backgrounds/iris-aluminium.png

echo "[5/7] Menyalin sesi Iris ke /usr/share/xsessions..."
install -d -m 0755 /usr/share/xsessions
cp -a "${REPO_DIR}/sessions/iris.desktop" /usr/share/xsessions/iris.desktop
chown root:root /usr/share/xsessions/iris.desktop
chmod 0644 /usr/share/xsessions/iris.desktop

echo "[6/7] Mengonfigurasi dconf (tema, panel, wallpaper)..."
if command -v dconf >/dev/null 2>&1; then
    # Muat pengaturan dconf untuk user target
    sudo -u "${TARGET_USER}" dconf load /org/cinnamon/ < "${REPO_DIR}/dconf/iris-settings" 2>/dev/null || true

    # Pastikan LightDM menggunakan greeter yang benar (jika ada konfigurasi)
    if [ -f /etc/lightdm/lightdm.conf ]; then
        sed -i 's/^#greeter-session=.*/greeter-session=lightdm-gtk-greeter/' /etc/lightdm/lightdm.conf
        sed -i 's/^#user-session=.*/user-session=cinnamon/' /etc/lightdm/lightdm.conf
    fi
fi

echo "[7/7] Mengaktifkan LightDM dan membersihkan..."
systemctl enable lightdm 2>/dev/null || true
systemctl restart lightdm 2>/dev/null || true

echo ""
echo "============================================================"
echo "Instalasi selesai!"
echo ""
echo "Langkah selanjutnya:"
echo "  1. Logout dari sesi saat ini."
echo "  2. Di layar login (LightDM), pilih sesi 'Iris'."
echo "  3. Login — desktop akan tampil dengan tema Aluminium OS."
echo ""
echo "Jika tampilan belum berubah, jalankan:"
echo "  gsettings set org.cinnamon.theme name 'Iris'"
echo "  gsettings set org.cinnamon.desktop.interface gtk-theme 'Iris'"
echo "============================================================"