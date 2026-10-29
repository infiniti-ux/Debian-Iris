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

**Ladder radius** (sama persis di `gtk-3.0`, `gtk-4.0`, dan `cinnamon.css` — angka-angka
ini ditulis literal di tiga file, jadi ubahnya pakai script, bukan satu-satu):

| Radius | Untuk |
|---|---|
| `18px` | window / surface luar: `decoration`, `window.ssd decoration`, `window.ssd headerbar.titlebar`, `window.csd decoration` |
| `20px` | sheet GTK: `menu`/`.popup`/`.context-menu`, `popover`, `.notification` |
| `24px` | drawer + semua dropdown shell: `.popup-menu-content`, `.menu` (satu node dipakai start menu, kalender, tray popup — semuanya ikut; disengaja) |
| `14px` | `entry`/`textview text`/`.view`, `row`, tile |
| `12px` | `menuitem`, `tooltip` |
| `22px` | `.info-osd`, `.osd` (kedua panel full-bleed, radius 0) |
| `999px` | chip/pill: `button`, `spinbutton`, `.sidebar row`, `.applet-box`, `.window-list-item-box`, `switch`, `.clock-widget`, scrollbar/slider |

Ritme spasi 4px: `row` `8px 12px`, `button` `7px 16px` (min-height 30), `menuitem` `8px 14px`,
headerbar CSD `min-height: 46px`. Hover menu **tonal** (`rgba(76,127,208,.18)`), bukan accent
penuh — row yang terisi penuh terbaca "selected", padahal itu state lain.
Tebal garis: 1px, kecuali indikator aktif taskbar 2px.

## 2. Permukaan & efek

| Permukaan | File | Efek | Catatan |
|---|---|---|---|
| Panel atas (30px) | `cinnamon/cinnamon.css` `.panel-top` | `rgba(15,17,23,.55)` + `background-blur: 10`, full-bleed, teks `#f2f4f7` + padding ramping (`1px 8px` / `0 4px`) via rule turunan `.panel-top …` | jam kiri + tray kanan; teks gelap base di-override semua — kalau ada yang ke-skip, bug-nya teks hilang di bar gelap |
| Taskbar bawah (60px) | `.panel-bottom` | putih `rgba(255,255,255,.97)`, `background-blur: 0`, hairline atas | menu + separator + grouped-window-list di tengah; state aktif/fokus tonal biru, bukan wash putih (nggak kelihatan di bar putih) |
| Menu applet & start menu | `.popup-menu-content`, `#menu-search-entry` | blur 12, radius 24, sheet lavender `rgba(224,227,234,.96)`, search pill putih | `background-blur` itu parse int, jadi `12` bukan `12px` |
| Notifikasi / OSD | `.notification`, `#notification`, `.info-osd`, `.switcher-list` | blur 12, radius 20 (OSD 22) | permukaan statis → aman |
| Frame window (SSD) | `gtk-3.0/gtk.css` `window.ssd decoration` + `window.ssd headerbar.titlebar` | radius 18 di **kedua** node, shadow `0 10px 28px 2px`, titlebutton bulat | Muffin membaca radius dari titlebar (lihat `docs/SAFETY.md` §3) |
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
tools/preview.py · preview-base.css       web mock: render dari CSS tema (make preview)
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
8. Selector yang mengenai banyak aplikasi (`toolbar.primary-toolbar`, `stackswitcher button`,
   `notebook tab`, dsb.) harus di-scope ke id widget aplikasi target — lihat §7. Kalau tidak,
   satu "percantik Settings" bisa ngilangin surface header app sebelah.

## 7. Aplikasi Settings (`cinnamon-settings`) — yang bisa dan tidak bisa di-CSS

Semua nama di bawah dibaca dari sumber upstream (`linuxmint/cinnamon`,
`files/usr/share/cinnamon/cinnamon-settings/`), bukan dari tebakan — ini bagian yang bikin
§6 relevan:

| Sumber | Isi yang dipakai sebagai hook CSS |
|---|---|
| `cinnamon-settings.ui` | `GtkBox#main_box` → `GtkToolbar#top_bar` (style class `primary-toolbar`) → `GtkStack#header_stack` berisi `GtkEntry#search_box` atau `GtkButton#button_back` + `GtkStackSwitcher#stack_switcher`; lalu `GtkStack#main_stack` → `GtkScrolledWindow#side_view_sw` (class `cs-category-view`, `view`, ditambah di `.py` baris 280-281) → `GtkBox#category_box`, dan `#content_box_sw` → `GtkBox#content_box` |
| `cinnamon-settings.py::prepCategory()` | tiap kategori = `GtkSeparator` + `GtkBox(GtkImage + GtkLabel)` + `GtkIconView`; item IconView digambar dengan `GTK_STYLE_CLASS_CELL` + state `selected`, dan cara resmi ngebulatin tile adalah `iconview:selected { border-radius }` (persis yang dilakukan Adwaita) |
| `bin/SettingsWidgets.py` | halaman modul diberi nama `c_box` |
| `libXApp` | node `stacksidebar` (+ `.sidebar`, row `.needs-attention`); `XAppPreferencesWindow` cuma nambah `.frame` / `.view` / `text-button` |

Yang Iris sentuh (`gtk-3.0/gtk.css` §13): header toolbar jadi permukaan aluminium transpar,
`#search_box` jadi pill "Search apps", `#stack_switcher` jadi segmented pill, `#button_back`
ghost circle, tile kategori M3 (tonal fill + radius 20 + hairline antar kategori), isi modul
jadi kartu (`frame` radius 18, hairline `separator`), `switch` rasio M3 (track 44×24 / knob 18),
row sidebar jadi pill — bagian terakhir ini juga kepakai di app XApp lain (Nemo prefs,
xlet-manager).

Yang **tidak** bisa: sidebar kiri permanen kayak screenshot. Cinnamon 6.x memang navigasi
dua-level — `main_stack` muter `side_view_page` ⇄ `content_box_page`, dan ukuran/spacing tile
di-set dari Python (`set_item_width`, `set_margin(20)`, `column_spacing 18`). CSS nggak bisa
pindahin widget antar halaman satu stack, jadi yang berubah itu *gaya*, bukan *tata letak*.

Kalau mau sama persis, dua jalur yang jujur:
1. patch `cinnamon-settings.py` jadi `Gtk.Paned`/flap + `stacksidebar` permanen → artinya fork
   `cinnamon` (melanggar prinsip "bukan fork", dan harus di-maintain tiap rilis Mint/Debian);
2. bikin app Level 1 sendiri ("Iris Control"): shell GTK3 kecil dengan sidebar M3 + search,
   tiap entri manggil `cinnamon-settings <module>` — skin tetap utuh, bisa dihapus tanpa sisa.
   Jalur ini yang direncanakan; lihat `docs/RESEARCH.md` (level 1) dan README "Status & arah".

## 8. `make preview` — cara theme dibaca ulang jadi web mock

`tools/preview.py` adalah penerjemah, bukan theme kedua:

- Parser: stripping komentar (dengan offset newline dipertahankan → nomor baris tetap benar),
  lalu tiap blok `selector { decls }`. `@define-color` di-parse terpisah dan `@iris_*`
  di-expand rekursif supaya warna yang dipakai mock memang warna tema.
- Parser top-level: statement di antara blok (`@define-color iris_accent #…;`) ikut ke-head
  blok berikutnya kalau head-nya nggak dipotong sampai `;` terakhir — tanpa itu, rule pertama
  sesudah blok token (di `gtk.css` itu `window { background; color; font-family }`) kebuang
  dan seluruh jendela kehilangan background + font. Jumlah `{` di file vs jumlah rule hasil
  parse selalu dicocokin waktu mengubah parser.
- Selector: `:hover` dibiarkan jadi pseudo asli (browser menangani hover di mock tanpa bantuan);
  `:focus`/`:active` dan state yang nggak bisa dipegang `<div>` (`:selected`, `:checked`,
  `:backdrop`, `:highlight`, `:dnd`, `:overview`) dipetakan ke class `.is-*` — kalau tidak,
  styling state-nya hilang diem-diem dan preview kelihatan "benar". JS preview nyalin
  `focusin`/`pointerdown` asli ke class `is-focused`/`is-active`, jadi mock tetap interaktif,
  dan klik tile/tab/switch mengubah `is-selected`/`is-checked`. Selector yang nyebut class widget
  St/Gtk (`StScrollBar StButton#vhandle`) ditandai "no mock node", bukan dipilih sepihak.
- Properti: yang punya padanan web disalin apa adanya; `background-blur`, `spacing`,
  `border-radius-topleft`, `-st-vfade-offset` didekati (daftar + alasannya di tab mapping);
  sisanya (`-gtk-icon-*`, `-GtkTreeView-*`) dilaporkan sebagai tak diterjemahkan.
  Urutan cek penting: tabel aproksimasi sebelum "ini nama properti web" — kalau tidak,
  `spacing` bocor jadi properti yang browser buang.
- Data non-CSS yang dipakai mock cuma satu: `panels-height` dari profil gsettings
  (`--iris-panel-height`), dan itu ditunjukkan di header CSS hasil generate.
- `preview-base.css` isinya geometri mock saja (flex/grid/posisi + chrome situs). Warna,
  radius, border, shadow sengaja tidak ada di situ, supaya "elemen X tampil polos" berarti
  temanya memang tidak punya rule buat X. Chrome situsnya sendiri sengaja **terang**:
  Iris tema terang dan banyak surface-nya `transparent` by design (menuitem, row,
  `.cs-category-view`), jadi di panggung gelap teksnya hilang dan mock terbaca rusak —
  itu bug panggung, bukan sinyal soal tema.

### 8.1 Audit reachability — kenapa GUI-nya nggak boleh "kira-kira"

Mock yang meleset separuh lebih buruk daripada tanpa mock: bagian yang nggak kena rule jatuh ke
`preview-base.css` (geometri, tanpa warna) dan terbaca sebagai "temanya jelek", padahal preview-nya
yang bolong. Jadi `tools/preview.py` punya audit:

1. generate CSS mock, render DOM mock (semua tab + varian state: `dim`, `hl`, `dnd`, selalu dengan `full: 1` — tab desktop default-nya product shot bersih, jadi auditnya maksa scene sampler penuh biar cakupannya nggak susut);
2. parse markup-nya sendiri jadi pohon node (tag soup, cukup untuk HTML yang ia generate sendiri);
3. cocokkan tiap selector hasil translasi terhadap pohon itu — bukan cuma token terakhir, tapi
   rantai ancestor dengan semantik `>` dan descendant, sambil mengabaikan pseudo runtime
   (`:hover`, `:focus`) dan class `is-hover/is-focused/is-active` yang disediakan browser/JS;
4. rule yang tetap nggak mendarat dikasih **auto-demo**: kotak kecil yang membawa class persis
   seperti selector-nya, muncul di tab **components**, lalu audit diulang.

`make preview-check` (`--print audit`) gagal kalau masih ada selector yang nggak mendarat, dan
gagal juga kalau jumlah auto-demo lewat `--max-demo 60` — naiknya angka itu artinya rule tema
berhenti mendarat di widget sungguhan (class di-rename upstream, atau node yang nggak pernah
dibangun), dan yang rusak pertama kali adalah desktopnya, bukan auditnya. Angka hari ini:
345 rule dipetakan, 32 cuma lewat auto-demo, 0 unreachable.
