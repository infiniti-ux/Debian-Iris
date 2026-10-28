# RESEARCH — bikin "desktop environment custom" dari nol: apa yang realistis

Riset per 2026-10-28. Setiap klaim diberi sumber; angka versi diverifikasi ke arsip Debian
dan repo upstream (bukan dari ingatan). Ringkasan: **iya, bisa** — tapi "DE custom" itu spektrum,
dan posisi yang masuk akal buat proyek ini adalah level 1–2 + 4, bukan level 3.

## 1. Konteks: Aluminium OS itu bukan Linux desktop

- Aluminium OS (codename; nama retail belum diumumkan) diumumkan Google 12 Mei 2026 di
  "The Android Show: I/O Edition", dibangun di atas **Android 17**, menggantikan ChromeOS di
  laptop konsumen (brand baru: *Googlebook*), perangkat pertama disebut **fall 2026** dari
  Acer/ASUS/Dell/HP/Lenovo, harga masuk >$999. ([techjournal](https://techjournal.org/google-aluminium-os-replacing-chromeos),
  [byteiota](https://byteiota.com/google-aluminium-os-developer-guide-2026/))
- Sisi UI: taskbar, virtual desktops, snap layout, Files dengan navigasi folder beneran,
  terminal Linux, extension Chrome. Desainnya adalah **Material 3 Expressive**: radius besar,
  bentuk campuran (bundar + kotak buat "visual tension"), 10 langkah skala radius, tonal color
  roles, motion berbasis fisika. ([supercharge](https://supercharge.design/blog/material-3-expressive),
  [Material 3](https://zoewave.medium.com/material-3-design-system-e91a15d303a0))
- Konsekuensi buat kita: yang boleh kita tiru adalah **bahasa visual** (radius, tonal palette,
  panel melayang, taskbar bawah, sidebar settings). Yang **tidak** bisa kita tiru adalah
  arsitekturnya (Android framework, AICore/NPU, Play Store). Jadi "Aluminium-flavored Cinnamon"
  = proyek tema + shell customization, bukan proyek OS. ChromeOS sendiri dipertahankan Google
  untuk education/enterprise ([eloutput](https://en.eloutput.com/news/applications/This-is-what-the-new-operating-system-will-be-like-in-Google's-aluminum-OS./)).
- Jangan menaruh screenshot leak Google di repo (hak cipta + bukan materi resmi). Sudah dihapus;
  lihat `docs/SAFETY.md` §1.11.

## 2. Status teknis yang relevan

| Topik | Fakta terverifikasi | Sumber |
|---|---|---|
| Cinnamon di Debian 13 trixie | `cinnamon-core 6.4.1` (source `cinnamon-desktop-environment`) | [packages.debian.org/trixie/cinnamon-core](https://packages.debian.org/trixie/cinnamon-core) |
| Cinnamon di sid/Debian 14 | `cinnamon 6.6.9-3`; `forky` sudah ada di daftar suite | [packages.debian.org/sid/cinnamon](https://packages.debian.org/sid/cinnamon) |
| Wayland di Cinnamon | eksperimental sejak 6.0; **6.8 melepas label "experimental"** (Mint 23, target Natal 2026), X11 tetap didukung dan tetap default | [tuxmachines](https://news.tuxmachines.org/n/2026-07-08/Linux_Mint_s_Cinnamon_6_8_Desktop_Environment_Will_Fully_Suppor.shtml), [The Register](https://forums.theregister.com/forum/all/2026-07-10/20265/), [daily.dev](https://daily.dev/posts/linux-mint-is-finally-ready-for-wayland-and-it-s-handling-the-switch-the-way-gnome-never-did-m7y22ggbz) |
| Cara Muffin me-frame window | Tidak ada parser `metacity-theme-*.xml`; frame dibangun dari GtkStyleContext bertema GTK (`window.ssd` > `decoration` > `headerbar`/`.titlebar.default-decoration`, `label.title`, `button.titlebutton`), dan radius klip dibaca dari `border-radius` node titlebar | `linuxmint/muffin` [`src/ui/theme.c`](https://github.com/linuxmint/muffin/blob/master/src/ui/theme.c) (`meta_theme_create_style_info`) |
| Blur di Cinnamon | properti CSS St `background-blur` (diparse sebagai int, hanya di grup `background-*`); ada extension pihak ketiga yang aktif `BlurCinnamon@klangman` untuk panel/menu/overview/notifikasi/jendela aplikasi, termasuk efek sudut membulat | st-theme-node.c di `linuxmint/cinnamon`; [Cinnamon Spices #104](https://cinnamon-spices.linuxmint.com/extensions/view/104), [deepwiki ringkasan](https://deepwiki.com/linuxmint/cinnamon-spices-extensions/3-visual-effects-extensions) |
| Batas blur | upstream (Clem) menyebut blur non-statik tuntut CPU tinggi; panel yang mem-blur harus redraw terus saat jendela lewat di belakangnya; kombinasi blur + radius besar bermasalah | [forum Mint #458480](https://forums.linuxmint.com/viewtopic.php?t=458480) |
| Blur di belakang jendela GTK | tidak ada jalur tema; `picom` bisa `corner-radius` + `blur-background` tapi **hanya di X11 dan bentrok dengan compositor aktif (Muffin)** | [picom manpage](https://picom.app/), [linuxcommandlibrary](https://linuxcommandlibrary.com/man/picom) |
| Sesi Wayland Cinnamon di Debian | hitam kalau `xwayland` tidak dipasang (`cinnamon-common` tidak Depends padanya) | Debian bug [#1147594](http://www.mail-archive.com/debian-bugs-dist@lists.debian.org/msg2121986.html) |
| Hyprland | **tidak ada di trixie**, ada di `trixie-backports`/`forky`/`sid` (0.56.2). Artinya jalur "glass + radius native" = harus backports/self-build | [packages.debian.org/sid/hyprland](https://packages.debian.org/sid/hyprland) |
| labwc | ada di Debian; filosofi eksplisit: "no-bling", panel/wallpaper/screenshot diserahkan ke klien (waybar, sfwbar, fuzzel, mako, swaybg, swaylock) | [repo labwc](https://github.com/Pxtl/labwc), [Gentoo wiki labwc](https://wiki.gentoo.org/wiki/Labwc) |
| wlroots dari nol | "±50k baris kode yang toh harus kamu tulis"; sway ~31k LOC C, Arcan ~185k; kompositor kecil "dari nol" itu proyek tahunan | [way-cooler book](https://way-cooler.org/book/wlroots_introduction.html), [r/linux thread](https://www.reddit.com/r/linux/comments/wwsiaf/writing_a_wayland_compositor_is_much_harder_than/), [wayland.fyi](https://wayland.fyi/) |
| Build ISO | `live-build` dengan layout `config/package-lists/*.list.chroot`, `config/includes.chroot/`, `config/hooks/`; build harus di distro target yang sama; ±13 GB workspace | [debian-live-config docs](https://debian-live-config.readthedocs.io/en/latest/custom.html), [marcocetica](https://marcocetica.com/posts/custom-live-system/) |
| Nama distro | derivatif **tidak boleh** dinamai "Debian"; logo Debian tidak boleh dipakai untuk distribusi hasil modifikasi | [Debian Derivatives Guidelines](https://wiki.debian.org/Derivatives/Guidelines) |

## 3. Spektrum "DE custom" — dari kulit sampai kompositor

| Level | Isi | Biaya riil | Hasil |
|---|---|---|---|
| **0. Theme pack** | GTK3/4 CSS + `cinnamon.css` + wallpaper + dconf/gsettings profile, didistribusikan sebagai `.deb` | minggu (sudah kita di sini) | desktop terlihat baru, 100% aman, mudah dibatalkan |
| **1. + shell customization** | applet/desklet/extension Cinnamon (JS/CJS + St, API `imports.ui.*`, Settings API) → menu custom, quick-settings, panel melayang, widget | 1–3 bulan untuk 3–4 applet rapi | inilah yang bikin terasa "DE sendiri", tetap di dalam Cinnamon |
| **2. Shell rakitan sendiri** | pilih kompositor + komponen: `labwc`/wlroots + waybar + fuzzel/wofi + mako + swaybg + swaylock + nemo/thunar; `.desktop` sesi sendiri, portal, config tema | 1–2 bulan untuk basis, lalu *maintenance seumur hidup* | kontrol penuh; tapi tidak ada blur panel-native di labwc (no-bling), dan integrasi (settings daemon, screencast, HiDPI) jadi PR kamu |
| **3. Kompositor sendiri** | wlroots / smithay (Rust) / `libweston`; harus menangani KMS/DRM, libinput, seat, xdg-shell, viewporter/HiDPI, Xwayland, screenshots, idle, layer-shell, DnD, IME | tahun engineer, dan kamu tetap ketinggalan protokol | cuma masuk akal kalau tujuannya belajar atau produk serius ber-team |
| **4. Distro/ISO** | `live-build` config + `config/includes.chroot` (tema, default gsettings, wallpaper, plymouth — lihat catatan), `hooks`, `task-lists`; opsi `.deb` repo sendiri; installer (live-debinstaller/calamares) | 2–4 minggu untuk pipeline yang bisa diulang | "Debian Iris" jadi image yang bisa dicoba orang |

Rekomendasi buat proyek ini: kunci **0+1** sebagai identitas, jadikan **4** sebagai output nyata
(ISO + repo `.deb`), dan **coba 2 sebagai eksperimen terpisah** (`iris-labwc` branch) kalau
tujuan utamanya Wayland. **Jangan** mulai 3 kecuali tujuannya memang belajar kompositor.

## 4. Dua jalur arsitektur yang layak dipertimbangkan dengan sungguh

**A. Jalur Cinnamon (posisi sekarang) — paling cepat terasa, paling sedikit kode.**
- Kelebihan: panel/taskbar/applet/settings daemon/Nemo sudah ada dan matang; sesi X11 solid di
  trixie; Wayland resmi di 6.8 → naik sendiri saat Debian 14 keluar.
- Batas yang tidak bisa ditembus tema: blur di belakang jendela aplikasi, animasi "springy"
  Material 3, shadow warna, shape morphing. Yang bisa: radius, nada warna tonal, panel kaca,
  menu, notifikasi, dan applet custom.

**B. Jalur wlroots rakitan (labwc + waybar) — kalau "glass di semua permukaan" itu inti proyek.**
- waybar/`layer-shell` memungkinkan radius + translucency konsisten, dan Hyprland (di backports)
  memberi blur + radius *native* untuk window — visual paling dekat dengan Aluminium OS.
- Harga: kamu yang menulis integrasi (audio, idle, portal, DPI, multi-monitor, autologin, power
  menu), dan kamu yang menanggung maintenance setiap wlroots API berubah.

## 5. Yang harus tetap jadi "punya kita"

Bahasa visual Aluminium bukan hak milik; **nama dan logo**-nya iya. Jadi:
boleh pakai radius besar, tonal light-grey, accent biru, taskbar bawah melayang, pill button;
jangan pakai kata "Aluminium OS" sebagai nama produk, jangan pakai aset Google, jangan claim
"reskin of Aluminium OS" di README (boleh: "inspired by").

Soal nama sendiri: `Debian-Iris` aman sebagai nama repo (menyebut Debian secara faktual), tapi
**image yang dirilis tidak boleh dinamai "Debian"**. Rencananya: produk = **Iris**, kalimat
resmi = "Iris, a desktop skin for Debian". Tambahkan atribusi SPI di README/docs kalau nanti
ada halaman unduhan.
