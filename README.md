# Debian-Iris

Custom Desktop Environment berbasis **Debian 13 (trixie)** dan **Cinnamon**, mengadopsi UI/UX **Google Aluminium OS** (rounded corners, glassmorphism/translucency, sidebar settings, taskbar bawah ala Windows).

## Tujuan
Membuat desktop environment ringan, modern, dan siap pakai langsung setelah `git clone` + jalankan satu script install.

## Arsitektur
| Komponen | Pilihan |
|---|---|
| Base OS | Debian 13 (trixie) amd64 |
| Desktop Environment | Cinnamon (core) |
| Window Manager | Muffin (bawaan Cinnamon) |
| Display Manager | LightDM |
| Panel / Taskbar | Cinnamon Panel (Windows-style, bawah layar) |
| File Manager | Nemo |
| Tema | Iris Theme (Aluminium OS inspired) |
| Session | `/usr/share/xsessions/iris.desktop` |

## Cara Pakai (Cepat)

```bash
# 1. Clone repo
git clone https://github.com/infiniti-ux/Debian-Iris.git
cd Debian-Iris

# 2. Jalankan installer (perlu hak root)
sudo ./scripts/install.sh

# 3. Logout, pilih sesi "Iris" di layar login LightDM, lalu login
```

Script installer akan:
- Menginstal `cinnamon-core`, `lightdm`, `papirus-icon-theme`, `bibata-cursor-theme`, dan dependensi lainnya
- Menyalin tema `Iris` ke `/usr/share/themes/Iris`
- Menyalin wallpaper ke `/usr/share/backgrounds/iris-aluminium.png`
- Menambahkan sesi "Iris" ke layar login (`/usr/share/xsessions/iris.desktop`)
- Mengonfigurasi dconf (tema, ikon, kursor, wallpaper, panel bawah)

## Menghapus Iris

```bash
sudo ./scripts/uninstall.sh
```

## Struktur Repo

```
Debian-Iris/
├── README.md
├── LICENSE
├── docs/DESIGN.md              # Spesifikasi desain lengkap
├── dconf/iris-settings        # Pengaturan dconf (tema, panel, wallpaper)
├── scripts/
│   ├── install.sh             # Installer otomatis (jalankan sebagai root)
│   └── uninstall.sh           # Uninstaller
├── sessions/iris.desktop      # File sesi untuk layar login LightDM
├── theme/Iris/                # Tema lengkap (index.theme, cinnamon.css, gtk.css, metacity)
│   ├── index.theme
│   ├── cinnamon/cinnamon.css
│   ├── gtk-3.0/gtk.css
│   └── metacity-1/metacity-theme-3.xml
└── wallpapers/iris-aluminium.png   # Wallpaper default (Aluminium OS style)
```

## Referensi Visual

Foto leak Aluminium OS disimpan di `image-search/` sebagai referensi desain (rounded corners, taskbar bawah, nuansa abu-abu metalic).

## Status

🚧 Tahap awal — sudah bisa diinstall dan digunakan. Silakan buat issue atau pull request untuk perbaikan tema, panel, atau daftar paket.