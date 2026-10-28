# Spesifikasi Desain — Debian Iris Desktop Environment

## Base
- **OS:** Debian 13 (trixie) amd64
- **Desktop Environment:** Cinnamon (core) + Muffin window manager
- **Display Manager:** LightDM
- **Session name:** `iris` (tampilkan sebagai "Iris" di layar login)

## Visual Reference — Aluminium OS (leaked)
Referensi utama: screenshot settings panel Aluminium OS yang ditempatkan di `image-search/google-aluminum-os-desktop-interface-chr-1.jpg`.

Ciri khas yang diadopsi:
- Window / panel dengan **rounded corners** dan translucency (glassmorphism)
- Warna dominan: abu-abu metalic (aluminium), background gradasi muda, accent biru soft
- Sidebar kiri di Settings (Network, Bluetooth, Account, Device, Apps, dll.)
- **Panel bawah berbentuk Windows taskbar** (bukan dock macOS): tombol Start/menu kiri, taskbar tengah, sistem tray + jam di kanan

## Komponen yang Dikustomisasi

| Komponen | Lokasi | Kustomisasi |
|---|---|---|
| Cinnamon panel (taskbar bawah) | `theme/cinnamon/cinnamon.css` | Windows-style taskbar, tinggi 40px, bg abu-abu metalic, rounded corners |
| GTK controls (tombol, input) | `theme/iris-gtk/gtk-3.0/gtk.css` | Warna aluminium, rounded input/button |
| Window borders (Muffin) | `theme/iris-muffin/metacity-theme-3.xml` | Border tipis, tombol minim/maximal/close ala modern |
| Icon theme | `theme/icons/` | Papirus/Bibata-based, konsisten aluminium |
| Cursor | Bibata-Modern-Classic | Sudah ada di Debian repositori |
| Wallpaper default | `theme/wallpapers/` | Gradasi aluminium/pastel |
| Plymouth bootsplash | `config/includes.chroot/usr/share/plymouth/themes/iris/` | Boot splash Iris |
| Session file | `sessions/iris.desktop` | Muncul di LightDM sebagai "Iris" |

## Panel Taskbar (Windows-style)
Berdasarkan referensi screenshot, panel bawah harus:
1. Posisi: bawah layar
2. Tinggi: 40px
3. Zona kiri: Menu Iris (Cinnamon menu), peluncur aplikasi
4. Tengah: daftar jendela terbuka (window list)
5. Kanan: sistem tray, jam, tanggal
6. Visual: bg `rgba(220, 220, 220, 0.85)`, border-radius 12px pada sudut atas, sedikit transparansi

## Session File
File `sessions/iris.desktop` akan diinstall ke `/usr/share/xsessions/iris.desktop` sehingga opsi "Iris" muncul di layar login LightDM/GDM3.

## Build (Opsional)
Jika ingin menghasilkan ISO installable, gunakan `live-build` dengan struktur di `config/`.