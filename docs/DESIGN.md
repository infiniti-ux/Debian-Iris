# DESIGN — spesifikasi Iris skin

Target: **Debian 13 (trixie) + Cinnamon 6.4.1**, naik-lurus ke Cinnamon 6.8 (Debian 14) tanpa
perubahan arsitektur. Rujukan visual: bahasa desain Material 3 Expressive seperti yang dipakai
Google di laptop Android-nya — radius besar, permukaan nada aluminium, satu aksen biru,
taskbar bawah melayang. Kita meniru **bahasa visual**, bukan produk atau asetnya
(lihat `docs/RESEARCH.md` §5).

## 1. Token

GTK3 CSS mendukung `@define-color`, jadi palet didefinisikan di sana.
**St/Cinnamon CSS tidak mendukungnya** → `cinnamon.css` menulis nilai literal; kalau warna
diubah, keduanya harus disinkronkan manual (sengaja, bukan kelalaian).

| Token | Nilai | Dipakai untuk |
|---|---|---|
| `iris_window` | `#eef0f3` | latar jendela, panel dasar |
| `iris_surface` | `#f7f8fa` | headerbar/titlebar, menu |
| `iris_base` | `#ffffff` | entry, tombol, list |
| `iris_fg` | `#1f2430` | teks utama (kontras > 7:1 di atas semua latar ini) |
| `iris_outline` | `#c6ccd4` | garis tepi 1px |
| `iris_accent` | `#4c7fd0` | fokus, seleksi, "pill" aktif, garis bawah taskbar item |
| `iris_destructive` | `#d1534a` | hover tombol close |
| `iris_shadow` | `rgba(40,48,62,.30)` | drop shadow window/menu |

Radius: `14px` window/frame · `12px` control (button/entry) · `16-18px` panel/menu/OSD ·
`999px` pill (titlebutton, search, toggle, badge).
Tebal garis: 1px, kecuali indikator aktif taskbar 2px.

## 2. Permukaan & efek

| Permukaan | File | Efek | Catatan |
|---|---|---|---|
| Panel bawah | `cinnamon/cinnamon.css` `.panel-bottom` | `rgba(236,238,241,.78)` + `background-blur: 14`, radius 18, margin 8 → melayang | blur di sini yang paling mahal; kalau frame rate turun saat jendela lewat, turunkan ke `background-blur: 6` atau hapus |
| Menu applet & start menu | `.popup-menu-content`, `#menu-search-entry` | blur 12, radius 16, search pill | `background-blur` itu parse int, jadi `12` bukan `12px` |
| Notifikasi / OSD | `.notification`, `#notification`, `.info-osd`, `.switcher-list` | blur 12, radius 16 | permukaan statis → aman |
| Frame window (SSD) | `gtk-3.0/gtk.css` `window.ssd decoration` + `window.ssd headerbar.titlebar` | radius 14 di **kedua** node, shadow, titlebutton bulat | Muffin membaca radius dari titlebar (lihat `docs/SAFETY.md` §3) |
| Headerbar CSD | `gtk-3.0/gtk.css` `headerbar` | permukaan datar, border bawah tipis | untuk app GTK yang menggambar titlebar sendiri |
| Window "glass" | `gtk-3.0/gtk-translucent.css` (opt-in) | translucent, **tanpa** blur | sadar batas: ini palsu; beberapa app akan smear |

Yang **tidak** dijanjikan: blur dinamis di bawah jendela app, shape morphing, motion physics,
dynamic color dari wallpaper. Tidak ada jalur tema untuk itu di Muffin; butuh fork C++ di
`muffin` (level 3 di `docs/RESEARCH.md` §3) — sengaja tidak dilakukan.

## 3. Tata letak panel (Windows-style, lihat `config/gsettings/iris.gsettings`)

```
[1:0:bottom]  tinggi 44px
  left   : menu@cinnamon.org · separator · panel-launchers@cinnamon.org
  center : window-list@cinnamon.org
  right  : systray · xapp-status · notifications · keyboard · network · sound · power
           · calendar · cornerbar(show-desktop)
```
Semua UUID di atas ada di `files/usr/share/cinnamon/applets/` Cinnamon 6.4.
Format: `panels-enabled=['1:0:bottom']`, `panels-height=['1:44']`,
`enabled-applets=['panel1:<zone>:<idx>:<uuid>', ...]`.

## 4. Sesi

- `iris.session` → `/usr/share/cinnamon-session/sessions/` (grup `[Cinnamon Session]`,
  `RequiredComponents=cinnamon;nemo-autostart;cinnamon-killer-daemon;`, `DesktopName=X-Cinnamon`).
- `iris.desktop` → `/usr/share/xsessions/`, `Exec=cinnamon-session --session iris`.
- Varian Wayland (`iris-wayland.*`) di-install **hanya** dengan `--with-session`, dan butuh
  `xwayland`.

`DesktopName` tidak boleh jadi `X-Iris`: komponen autostart Cinnamon ber-`OnlyShowIn=X-Cinnamon`.

## 5. Struktur file

```
theme/Iris/index.theme                    metatheme [X-GNOME-Metatheme]: GtkTheme/IconTheme/ButtonLayout
theme/Iris/cinnamon/cinnamon.css          shell St theme (satu-satunya tempat blur bisa dipakai)
theme/Iris/gtk-3.0/gtk.css                app + Muffin SSD frames
theme/Iris/gtk-3.0/gtk-translucent.css    opt-in translucent
theme/Iris/gtk-4.0/gtk.css                app GTK4 (bukan frame SSD — itu selalu dari gtk-3.0)
config/gsettings/iris.gsettings           profil tersetujui-schema
config/package-lists/iris-core.list.chroot daftar paket (live-build + --packages)
scripts/install.sh · uninstall.sh · apply-settings.sh · lib/common.sh
sessions/*.desktop · sessions/*.session   opsi "Iris" di layar login
tools/check-theme.py · gen-selectors.py   gerbang kualitas (make check)
debian/                                   .deb = cara install yang sebenarnya
```

## 6. Konvensi yang dijaga CI

1. Tidak ada nama selector di `cinnamon.css` yang tidak ada di `tools/upstream-selectors.txt`
   (+ `verified-selectors.txt` dengan bukti).
2. Tidak ada `@define-color`/`var()`/`!important`/`backdrop-filter` di `cinnamon.css`; tidak ada
   `* {}` global di gtk CSS; tidak ada `alpha(r,g,b,a)` (harus `rgba()`).
3. Tidak ada `metacity-1/`, `gnome-shell/`, atau direktori tema mati lain.
4. `index.theme` wajib punya `[X-GNOME-Metatheme]`.
5. `.session` wajib `DesktopName=X-Cinnamon`; `.desktop` wajib punya `--session <nama>` di Exec.
6. `config/gsettings/*` hanya berisi schema/key yang dikenal; key yang terbukti tidak ada di
   upstream ditolak sebagai error.
7. Nama paket di `config/package-lists/*` harus benar-benar ada di arsip Debian.
