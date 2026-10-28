# Debian-Iris

Custom Desktop Environment berbasis **Debian 13 (trixie)** dan **Cinnamon**, mengadopsi UI/UX **Google Aluminium OS** (rounded corners, glassmorphism/translucency, sidebar settings, dock bawah ala macOS/ChromeOS).

## Tujuan
Membuat desktop environment ringan, modern, dan mudah dikustomisasi yang tampil sebagai opsi sesi tersendiri di layar login (LightDM/GDM3), bernama "Iris".

## Arsitektur
| Komponen | Pilihan |
|---|---|
| Base OS | Debian 13 (trixie) amd64 |
| Desktop Environment | Cinnamon (core) |
| Window Manager | Muffin (bawaan Cinnamon) |
| Display Manager | LightDM |
| Panel / Taskbar | Cinnamon Panel (kustom CSS) |
| File Manager | Nemo |
| Tema | Iris Theme (Aluminium OS inspired) |
| Session | `/usr/share/xsessions/iris.desktop` |

## Struktur Repo
```
Debian-Iris/
├── README.md
├── LICENSE
├── docs/                 # Spesifikasi desain & panduan build
├── theme/                # Sumber tema kustom (cinnamon.css, gtk.css, ikon, wallpaper)
├── sessions/             # File .desktop untuk sesi Iris di layar login
├── config/               # Konfigurasi live-build (opsional, untuk build ISO)
│   ├── package-lists/
│   ├── hooks/
│   └── includes.chroot/
└── scripts/              # Skrip post-install & setup otomatis
```

## Status
🚧 Tahap awal — dokumentasi & struktur repo sedang disiapkan. Belum ada build ISO.

## Cara Kontribusi
Silakan buat issue atau pull request untuk penambahan tema, konfigurasi panel, atau daftar paket.