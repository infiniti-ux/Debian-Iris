# Iris

Desktop skin untuk **Debian 13 (trixie) + Cinnamon**, terinspirasi bahasa visual
Material 3 Expressive / laptop Google terbaru: permukaan aluminium terang, sudut membulat,
panel kaca melayang di bawah.

Bukan fork Cinnamon, bukan kompositor baru. Iris = tema + profil setting + sesi, dibungkus
`.deb`, dengan gerbang kualitas supaya tidak ada lagi config "kelihatan benar tapi nggak
berfungsi". (Kenapa itu keputusan yang tepat: [`docs/RESEARCH.md`](docs/RESEARCH.md).)

```
Debian 13 trixie  →  Cinnamon 6.4.1  →  Muffin (WM)  →  Nemo  →  LightDM/GDM
                        ↑ Iris menyalakan: cinnamon.css, gtk-3.0/4.0, gsettings, iris.session
```

## Coba cepat

```bash
git clone https://github.com/infiniti-ux/Debian-Iris.git
cd Debian-Iris

make check                     # validasi statis: selector, schema, desktop file, shell
make preview                   # lihat hasilnya di browser, di-generate dari file CSS-nya
make rice                      # pakai skin-nya di sesi Cinnamon kamu, tanpa root/.deb/ISO
make unrice                    # kembalikan semua yang diubah `make rice`
```

`make rice` cuma dua hal: symlink `~/.themes/Iris` ke checkout ini, lalu tulis profil gsettings
ke sesi yang sedang jalan (nilai lamamu di-backup dulu, efeknya live tanpa logout). Bukan
instalasi sistem — kalau Cinnamon-mu dari distro dan sudah jalan, ini jalur yang benar.

Butuh sesi login sendiri + entry LightDM + `.deb` (jalur turunan distro)? Baru pakai installer:

```bash
sudo ./scripts/install.sh --dry-run --with-session --with-lightdm   # lihat rencana, tidak menulis
sudo ./scripts/install.sh --all
```

`--all` = pasang file tema + sesi + drop-in LightDM + profil gsettings (untuk user yang lagi
login). Setelah itu **logout → pilih "Iris" di layar login**.

Dua hal yang sengaja **tidak** dilakukan diam-diam oleh installer:

| Kalau kamu mau | Tambahkan | Kenapa tidak default |
|---|---|---|
| Pasang paket Cinnamon/LightDM | `--packages` | Mengganti DE saat sesi aktif = layar blank; ditolak kecuali `--force` |
| Jadikan Iris sesi default di greeter | `--with-lightdm` | Tidak pernah menulis `/etc/lightdm/lightdm.conf`; hanya drop-in `lightdm.conf.d/60-iris.conf`, dan ditolak kalau GDM/SDDM yang aktif |

Bongkar pasangannya (presisi, bukan `rm -rf`):

```bash
sudo ./scripts/uninstall.sh --restore-settings
```

## Cara yang lebih benar: pakai .deb

```bash
sudo apt install debhelper devscripts
dpkg-buildpackage -us -uc -b
sudo apt install ../iris-theme_0.2.0_all.deb
sudo -u "$USER" iris-apply-settings      # dari dalam sesi desktop
```

Paket memasang tema ke `/usr/share/themes/Iris`, wallpaper, file sesi, dan
`/usr/share/iris/config/gsettings/iris.gsettings`. Konfigurasi display manager tidak
disentuh — `/etc/lightdm/lightdm.conf` tidak pernah ditulis ulang oleh apa pun di repo ini.

## Gerbang kualitas (CI)

Tiga job di [`.github/workflows/ci.yml`](.github/workflows/ci.yml), semuanya di container
`debian:trixie` — diverifikasi di Debian 13 betulan, bukan `ubuntu:latest`:

| Job | Apa yang dibuktikan |
|---|---|
| validate theme + configs | `make check` + `make check-strict`: tiap selector `cinnamon.css` harus ada di upstream Cinnamon/Mint-Y, tiap key gsettings harus ada di schema & UUID applet harus nyata, tiap nama paket harus ada di trixie, `index.theme`/`.desktop`/`.session` sah, `bash -n` bersih. `shellcheck --severity=error` memblokir; temuan level warning jadi catatan saja, supaya verdict tidak berubah mengikuti versi linter |
| install / uninstall round-trip | install betulan → file tema + sesi + drop-in LightDM ada → `--dry-run` terbukti tidak menulis apa pun → uninstall → semua hilang, dan `grep -q iris /etc/lightdm/lightdm.conf` harus gagal |
| build .deb | `dpkg-buildpackage` (menjalankan `make check` sebagai `dh_auto_test`, jadi `.deb` yang isinya rusak tidak bisa dibangun) → `dpkg -i` → 10 path wajib di-assert terhadap `dpkg -L`, dan `install.sh`/`metacity-1` harus **tidak** ada di dalam paket → `lintian` (saat ini 0 error / 0 warning; kalau ada temuan, dia muncul sebagai anotasi di review, tidak dibungkam) |

Jadi klaim "config-nya berfungsi" di repo ini bukan opini: selector, key, dan nama paket
dicek ke sumber upstream sebelum merge, dan installer/uninstaller dijalankan end-to-end.

## Mengatur setting saja

```bash
./scripts/apply-settings.sh --dry-run                 # apa yang akan berubah
./scripts/apply-settings.sh                           # terapkan + simpan cadangan nilai lama
./scripts/apply-settings.sh --restore ~/.local/share/iris/settings-backup/<file>
```

Setiap baris profil diverifikasi terhadap **schema yang terpasang**; key yang tidak dikenal
Cinnamon dilewati dengan peringatan (bukan ditulis diem-diem jadi sampah dconf).

## Lihat hasilnya tanpa VM: `make preview`

`tools/preview.py` nge-serve mock desktop Cinnamon (panel melayang, menu, kalender,
notifikasi, OSD, jendela, dan Settings app) yang **styling-nya di-parse langsung dari
`theme/Iris/cinnamon/cinnamon.css` + `gtk-3.0/gtk.css`** tiap request — jadi nggak ada
nilai yang disalin tangan, dan edit CSS → reload → berubah.

```bash
make preview                 # http://localhost:8080   (PORT=9000 make preview buat pindah)
```

Yang bikin ini bukan sekadar mockup cantik:
- **tiap rule tema harus mendarat di elemen mock.** Preview punya audit internal: DOM mock
  disusun, tiap selector dicocokin ke pohon node (termasuk rantai ancestor), dan yang nggak
  mendarat dipaksa kelihatan sebagai "auto-demo" di tab components — bukan didiemin.
  `make preview-check` jadi gerbang di CI (hari ini: 328 rule dipetakan, 0 unreachable);
- tab **components** nge-render kontrol asli satu-satu (button + variant, entry/focus, switch M3,
  checkbox, notebook tab, treeview/sidebar, scale/levelbar/progressbar/scrollbar, infobar, tooltip,
  popover, dialog, systray, window-list & grouped-window-list, appmenu, expo/overview, nemo)
  pakai nama class yang memang dipakai widget aslinya;
- tab **mapping** daftar tiap rule tema → elemen mock, dan yang *nggak* bisa diterjemahkan
  dilaporkan, bukan dibuang diem-diem;
- tab **source** nge-highlight baris CSS yang beneran nyetir render;
- panel kontrol: blur, alpha surface, skala radius, posisi panel, state backdrop, panel
  highlight/dnd, node labels;
- `:hover` jalan beneran di browser, `:focus`/`:active` disalin dari event ke class yang
  dicek tema, dan klik tile/tab/switch ngubah `:selected` / `:checked`;
- `--iris-panel-height` dibaca dari `config/gsettings/iris.gsettings`, bukan dikarang.

Jujur: ini **bukan** renderer GTK/St. Font hinting, biaya blur asli Clutter, dan clip frame
Muffin beda — pakai ini buat ngecek layout/warna/radius/hierarki, rasa aslinya tetap di sesi
beneran (daftar deviasinya ada di tab mapping).

## Kaca / blur — apa yang bisa dan tidak bisa

| Permintaan | Status |
|---|---|
| Panel & menu blur/translucent | ✅ `background-blur` di `cinnamon.css` (properti St khusus Cinnamon, mahal — kecil-kecil saja) |
| Sudut jendela membulat | ✅ lewat CSS GTK di node yang dibaca Muffin (`window.ssd decoration` + `headerbar`); **bukan** metacity XML, yang sudah tidak diparse Muffin sama sekali |
| Settings app ("Search apps" + list row ala screenshot) | ✅ di-skin lewat hook yang diverifikasi dari sumber `cinnamon-settings` (`#top_bar`, `#search_box`, `#stack_switcher`, `#category_box`, `iconview:selected`) — tapi layout-nya tetap dua-level Cinnamon; sidebar permanen butuh patch Python / app sendiri, lihat `docs/DESIGN.md` §7 |
| Blur di belakang jendela aplikasi | ❌ tidak ada jalur tema di Muffin; `picom` cuma X11 dan bentrok dengan compositor aktif. Alternatif opt-in: `gtk-3.0/gtk-translucent.css` (translucent, tanpa blur) |
| Semua app GTK4/Adwaita ikut tema | ⚠️ sebagian; app libadwaita menarik palette sendiri |
| Blur panel + radius besar + app window sekaligus, rata | itu Hyprland, yang di trixie cuma ada di `trixie-backports` — lihat opsi jalur di `docs/RESEARCH.md` §4 |

## Wayland

Sesi `Iris (Wayland)` tersedia lewat `--with-session` dan **wajib** ada paket `xwayland`;
tanpa itu desktop hitam (Debian [#1147594](https://bugs.debian.org/1147594): `cinnamon-common`
tidak menariknya). Di Cinnamon 6.4 statusnya masih eksperimental; Cinnamon 6.8 melepas label itu.

## ISO

`config/` sudah sesuai struktur `live-build` (`package-lists/*.list.chroot`,
`hooks/05-iris-defaults.chroot` untuk bake default dconf ke image). Build harus dilakukan di
mesin Debian trixie:

```bash
sudo apt install live-build && make iso
```

## Struktur

```
theme/Iris/          index.theme, cinnamon/cinnamon.css, gtk-3.0/{gtk,gtk-translucent}.css, gtk-4.0/gtk.css
config/             gsettings profile · live-build package list · hooks
sessions/           iris.{desktop,session} + varian Wayland
scripts/            install.sh · uninstall.sh · apply-settings.sh · lib/common.sh
tools/              check-theme.py (validator) · gen-selectors.py · preview.py (web mock) · daftar selector upstream
wallpapers/         iris-aluminium.png
docs/               DESIGN.md · RESEARCH.md · SAFETY.md
debian/             .deb (iris-theme)
```

## Status & arah

- ✅ Level 0: skin penuh + `.deb` + validasi + uninstall bersih
- 🚧 Level 1: applet/extension custom (quick settings, menu ala M3) — developer Cinnamon JS
- 🚧 Level 4: pipeline ISO yang bisa diulang + repo `.deb`
- 💭 Level 2 (eksperimen): rakitan `labwc` + `waybar` kalau goal utamanya Wayland

Lihat [issues](https://github.com/infiniti-ux/Debian-Iris/issues) dan `docs/SAFETY.md`
sebelum mengubah config sistem apa pun.

## Catatan nama

Iris bukan produk atau afiliasi Debian maupun Google. "Debian" adalah merek dagang SPI;
image hasil turunan tidak boleh dinamai "Debian". Logo/screenshot Google tidak dipakai dan tidak
distribusikan di repo ini.

## Lisensi

MIT untuk tema, skrip, dan dokumen. `tools/upstream-selectors.txt` adalah daftar *nama* selector
yang diekstrak otomatis dari Cinnamon/Mint-Y (GPL-2.0+) untuk keperluan interoperabilitas —
tidak ada aturan gaya yang disalin. Detail di `debian/copyright`.
