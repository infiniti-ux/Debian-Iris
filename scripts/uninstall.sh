#!/bin/bash
# =============================================================================
# scripts/uninstall.sh — Hapus Desktop Environment Iris
# Usage: sudo ./scripts/uninstall.sh
# =============================================================================
set -euo pipefail

echo "[1/3] Menghapus tema Iris dari /usr/share/themes..."
rm -rf /usr/share/themes/Iris

echo "[2/3] Menghapus wallpaper dan sesi Iris..."
rm -f /usr/share/backgrounds/iris-aluminium.png
rm -f /usr/share/xsessions/iris.desktop

echo "[3/3] Selesai. Iris telah dihapus."
echo "Pilih sesi lain (Cinnamon, GNOME, dll.) di layar login."