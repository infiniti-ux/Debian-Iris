#!/bin/bash
# =============================================================================
# scripts/install.sh — Debian Iris Desktop Environment Installer
# Base: Debian 13 (trixie) + Cinnamon Core + Aluminium OS inspired UI
# PERINGATAN: JALANKAN DARI TERMINAL TEKS (Ctrl+Alt+F2), JANGAN sambil login di desktop
# Usage: sudo ./scripts/install.sh
# =============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_USER="${SUDO_USER:-$USER}"
USER_HOME="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"

echo "============================================================"
echo "PERINGATAN: Debian Iris Desktop Environment Installer"
echo "============================================================"
echo ""
echo "JANGAN jalankan script ini sambil lagi login di desktop/Cinnamon."
echo "Jalankan dari terminal teks (Ctrl+Alt+F2) atau sebelum masuk desktop."
echo "Setelah selesai, REBOOT manual sendiri."
echo ""
echo "Tekan ENTER untuk lanjutkan, atau Ctrl+C untuk batal."
read -r

# Cek apakah sedang dalam sesi grafis
if [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ] || [ -n "${XDG_SESSION_TYPE:-}" ]; then
    echo ""
    echo "⚠️  Terdeteksi Anda sedang dalam sesi grafis ($XDG_SESSION_TYPE)."
    echo "   MATIKAN DESKTOP DULU sebelum melanjutkan."
    echo "   Tekan Ctrl+C untuk batal, atau ENTER untuk paksa lanjut (resiko blank screen)."
    read -r
fi

echo "[1/7] Memperbarui daftar paket..."
apt-get update

echo "[2/7] Menginstal dependensi inti (Cinnamon, LightDM, tema, dll)..."
DEBIAN_FRONTEND=noninteractive apt-get install -y \
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
    dconf-cli \
    gsettings-desktop-schemas

echo "[3/7] Backup konfigurasi LightDM lama (kalau ada)..."
if [ -f /etc/lightdm/lightdm.conf ]; then
    cp -a /etc/lightdm/lightdm.conf /etc/lightdm/lightdm.conf.bak.$(date +%Y%m%d%H%M%S)
fi

echo "[4/7] Menyalin tema Iris ke /usr/share/themes..."
install -d -m 0755 /usr/share/themes/Iris
cp -a "${REPO_DIR}/theme/Iris/." /usr/share/themes/Iris/
chown -R root:root /usr/share/themes/Iris
chmod -R 0755 /usr/share/themes/Iris

echo "[5/7] Menyalin wallpaper ke /usr/share/backgrounds..."
install -d -m 0755 /usr/share/backgrounds
cp -a "${REPO_DIR}/wallpapers/iris-aluminium.png" /usr/share/backgrounds/iris-aluminium.png
chown root:root /usr/share/backgrounds/iris-aluminium.png
chmod 0644 /usr/share/backgrounds/iris-aluminium.png

echo "[6/7] Menyalin sesi Iris ke /usr/share/xsessions..."
install -d -m 0755 /usr/share/xsessions
cp -a "${REPO_DIR}/sessions/iris.desktop" /usr/share/xsessions/iris.desktop
chown root:root /usr/share/xsessions/iris.desktop
chmod 0644 /usr/share/xsessions/iris.desktop

echo "[7/7] Menulis konfigurasi LightDM (wajib LightDM)..."
cat > /etc/lightdm/lightdm.conf << 'EOF'
[Seat:*]
greeter-session=lightdm-gtk-greeter
user-session=cinnamon
EOF

echo ""
echo "Mengatur dconf (tema, panel, wallpaper)..."
if [ -f "${REPO_DIR}/dconf/iris-settings" ]; then
    # Coba muat dconf untuk user target, tapi jangan gagalkan install jika error
    sudo -u "${TARGET_USER}" dconf load /org/cinnamon/ < "${REPO_DIR}/dconf/iris-settings" 2>/dev/null || {
        echo "⚠️  dconf load gagal (mungkin belum ada session D-Bus)."
        echo "   Atur tema secara manual setelah reboot via System Settings."
    }
fi

echo ""
echo "============================================================"
echo "Instalasi selesai!"
echo ""
echo "Langkah WAJIB selanjutnya:"
echo "  1. REBOOT komputer Anda sekarang: sudo reboot"
echo "  2. Di layar login LightDM, pilih sesi 'Iris'."
echo "  3. Login — desktop akan tampil dengan tema Aluminium OS."
echo ""
echo "Jika LightDM gagal nyala, periksa:"
echo "  sudo systemctl status lightdm"
echo "  sudo journalctl -u lightdm -n 30 --no-pager"
echo "============================================================"