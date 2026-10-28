# SAFETY — apa yang sebelumnya berbahaya, dan aturan yang sekarang berlaku

Dokumen ini ada karena repo ini pernah berisi config yang **kelihatan** benar tapi
bisa merusak desktop Cinnamon siapa pun yang menjalankannya. Semua klaim di bawah
sudah diverifikasi ke sumber upstream (repositori `linuxmint/*` dan arsip Debian),
bukan dari ingatan model.

## 1. Yang sudah dihapus / ditulis ulang

| # | Barang lama | Kenapa berbahaya | Sekarang |
|---|---|---|---|
| 1 | `scripts/install.sh` menulis ulang `/etc/lightdm/lightdm.conf` penuh + `user-session=cinnamon` | Menghapus seluruh konfigurasi LightDM milik pengguna (autologin, greeter, seat rules). Kalau `Iris` tidak terdaftar sebagai sesi → login screen gagal, pengguna terkunci di luar desktop. | Tidak pernah menyentuh `lightdm.conf`. Drop-in `/etc/lightdm/lightdm.conf.d/60-iris.conf`, hanya ditulis saat `--with-lightdm`, dan ditolak kalau display manager aktif bukan lightdm. |
| 2 | Installer `apt-get install cinnamon-core ...` secara default, dan hanya "mengingatkan" soal sesi grafis | Mengganti DE aktif saat user sedang login = skenario blank screen. Peringatan `read -r` juga bikin script macet/mati saat dijalankan non-interaktif (stdin tertutup). | Install paket jadi **opt-in** (`--packages`) dan **ditolak keras** kalau `loginctl` melihat sesi grafis aktif, kecuali `--force`. |
| 3 | `dconf load /org/cinnamon/ < dconf/iris-settings` dijalankan sebagai root lewat `sudo -u` | `dconf` butuh session bus milik user. Tanpa itu perintah gagal, tapi script menelan error (`|| echo ...`) lalu melaporkan "selesai". Hasilnya: desktop setengah terkonfigurasi, dan kalau berhasil ia menimpa pilihan user lain di subtree yang sama. | `scripts/apply-settings.sh` memvalidasi tiap `schema`+`key` terhadap schema yang **terpasang**, menyimpan nilai lama ke file backup (bisa `--restore`), dan **berhenti dengan pesan jelas** kalau tidak ada session bus. |
| 4 | Kunci inventif di `dconf/iris-settings`: `org.cinnamon theme`, `panel-positions`, `panel-heights`, `interface color-scheme`, `document-font-name`, `monospace-font-name`, `background show-desktop-icons`, `notifications icon-size` | Tidak ada di schema Cinnamon → `dconf` tetap menulisnya tanpa error, tapi tidak ada yang membacanya. Ini sampah config permanen di dconf user. | Habis. Nilai benar: `org.cinnamon.theme name`, `panels-enabled ['1:0:bottom']`, `panels-height ['1:44']`, `show-desktop-icons` ada di `org.nemo.desktop`. Diverifikasi ke `data/org.cinnamon.gschema.xml`, `schemas/org.cinnamon.desktop.*.gschema.xml.in`, `libnemo-private/org.nemo.gschema.xml`. |
| 5 | `enabled-applets` memakai `launchers@cinnamon.org` dan `clock@cinnamon.org` | Dua-duanya bukan applet Cinnamon → panel hilang item dan `cinnamon` log "applet not found". Applet asli: `panel-launchers@cinnamon.org`, `calendar@cinnamon.org`. | Diperbaiki; `tools/check-theme.py` menolak UUID di luar daftar applet upstream. |
| 6 | `theme/Iris/metacity-1/metacity-theme-3.xml` (border window "rounded_top_left=12") | Muffin **tidak punya parser metacity XML lagi** — nol referensi `metacity-theme` di seluruh repo `linuxmint/muffin`. Frame window justru diambil dari CSS GTK (`window.ssd > decoration > headerbar`), dan radius klip dibaca dari `border-radius` node *titlebar*. File ini mati total. | Direktori dihapus. Rounded window ditulis di `gtk-3.0/gtk.css` pada node yang benar, dengan komentar kenapa. |
| 7 | `cinnamon.css` lama memakai `.panel`, `.window-list-item`, `.menu-button`, `.clock`, `.app-launcher`, `.notification`, `border-top-left-radius` | 6 selector tidak ada di Cinnamon (yang ada `.window-list-item-box`, `.clock-widget`/`.clock-time-label`, `.panel-launchers`, `#panel`, `.popup-menu-content`) dan `border-top-left-radius` bukan properti St → seluruh file praktis tidak berpengaruh. | Ditulis ulang memakai daftar nama dari upstream + validator yang menolak nama karangan. |
| 8 | `config/package-lists/iris-core.list.chroot` berisi `plymouth-theme-iris` dan `nm-applet` | Keduanya bukan paket Debian. `lb build` gagal di tahap chroot; `nm-applet` binary ada di dalam `network-manager-gnome`. Menginstal theme Plymouth yang salah juga bisa membuat boot splash hang — kegagalan yang paling mahal untuk dipulihkan. | Entri dihapus. `plymouth` tidak pernah disentuh installer. |
| 9 | `sessions/iris.desktop` berisi `Exec=/usr/bin/cinnamon-session` | Upstream memakai wrapper `cinnamon-session-cinnamon` yang menjalankan `cinnamon-session --session cinnamon`. Tanpa `--session`, daftar komponen tidak dibaca → sesi "Iris" boot tanpa nemo-desktop/killer-daemon. | `Exec=cinnamon-session --session iris` + `/usr/share/cinnamon-session/sessions/iris.session` (grup `[Cinnamon Session]`, `DesktopName=X-Cinnamon` — wajib, lihat §3). |
| 10 | `uninstall.sh` = `rm -rf /usr/share/themes/Iris` + hapus wallpaper/sesi, tanpa memulihkan apa pun | User yang meng-uninstall ditinggali dengan LightDM yang sudah dirusak (#1) dan tema yang tetap aktif di dconf (#3). | uninstall berbasis **manifest** + marker kepemilikan `.iris-owned`, memulihkan file yang pernah ditimpa, dan menolak menghapus apa pun di luar allowlist / tanpa marker. |
| 11 | `image-search/google-aluminum-os-*.jpg/webp` (leak screenshot Google) | Bukan risiko teknis, tapi risiko hukum buat repo publik: itu materi berhak-cipta Google yang bocor, dan README menyebutnya "referensi resmi". | Dihapus dari repo (masuk `.gitignore`). Referensi desain dituliskan sebagai **deskripsi tekstual** di `docs/DESIGN.md`. |

## 2. Aturan yang sekarang mengikat repo ini

1. **Jangan pernah menimpa file config global.** Pakai drop-in (`/etc/…/*.d/`), atau tulis
   default lewat paket. Kalau terpaksa, backup dulu dan catat di manifest.
2. **Tidak ada perintah yang mengubah DE/DM/paket secara default.** Semua jalur destruktif
   di belakang flag eksplisit (`--packages`, `--with-lightdm`, `--with-session`).
3. **Setiap kunci konfigurasi harus diverifikasi terhadap schema yang terpasang**, bukan
   terhadap ingatan. Validator saat-install (`apply-settings.sh`) + validator statis
   (`tools/check-theme.py`).
4. **Setiap nama selector CSS harus ada di `tools/upstream-selectors.txt`.** Nama yang tidak
   ada = aturan mati, bukan "nanti juga jalan".
5. **Uninstall harus presisi**: manifest + marker kepemilikan + allowlist prefix, dan tidak
   pernah `rm -rf` path hasil string interpolation.
6. **Jangan sentuh Plymouth** dari repo tema.
7. **Jangan distribusikan materi berhak-cipta pihak ketiga** (screenshot leak, ikon berlisens).
8. `--dry-run` harus tersedia untuk semua operasi dan menampilkan rencana yang sama persisnya
   dengan eksekusi nyata.

## 3. Jebakan yang paling sering salah ditebak (simpan ini)

- **`DesktopName` sesi wajib `X-Cinnamon`.** Mengarang `X-Iris` bikin semua entri
  `OnlyShowIn=X-Cinnamon` (termasuk komponen autostart Cinnamon sendiri) dilewati → sesi
  hilang panel/settings daemon. Ini persis tipe "kerusak desktop" yang dimaksud.
- **Sesi Wayland Cinnamon butuh paket `xwayland`.** `cinnamon-common` mengirim
  `cinnamon-wayland.desktop` tanpa Depends `xwayland` (Debian bug #1147594): desktop jadi
  hitam karena `nemo-desktop` adalah klien X11.
- **Cinnamon `St` CSS ≠ CSS web ≠ GTK CSS.** Tidak ada `@define-color`, `var()`,
  `!important`, `transition`, `backdrop-filter`. Radius per-sudut namanya
  `border-radius-topleft` (bukan `border-top-left-radius`). Blur namanya `background-blur: <int>`.
- **Blur Cinnamon itu mahal.** Panel yang mem-blur butuh redraw tiap jendela lewat di
  belakangnya; upstream sendiri mencatat blur lebih sehat tanpa radius besar. Jangan pasang
  blur di permukaan yang statis-over-window tanpa alasan.
- **GTK tidak bisa mem-blur di belakang jendela.** Yang bisa dilakukan tema GTK adalah
  *translucent*, bukan glass — karena itu `gtk-translucent.css` di sini opt-in, bukan default.
- **`libadwaita` sebagian besar kebal terhadap tema GTK.** Aplikasi Adwaita/GTK4 modern
  menarik palette sendiri; "semua app otomatis ikut tema Iris" bukan janji yang bisa ditepati.
- **Muffin membaca radius frame dari node titlebar.** Kalau `decoration` dibulatkan tapi
  `headerbar` tidak, isinya keluar dari sudut bundar.
