#!/usr/bin/env python3
"""tools/check-theme.py — static checks for the Iris desktop skin.

This exists to catch the failure mode that a "just generate it" workflow
produces: config that *looks* right and is silently inert (or destructive) —
invented dconf keys, CSS selectors Cinnamon does not have, a metacity XML file
Muffin stopped parsing years ago, package names Debian has never shipped.

It checks only what can be checked without a running desktop; anything that
needs the live system is verified at install time by scripts/apply-settings.sh.

Usage:  tools/check-theme.py [--root .] [--strict]
Exit:   1 on errors (warnings only -> 0, or 1 with --strict)
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

# --- Cinnamon's St CSS engine does not understand these, GTK does -----------
BANNED_IN_CINNAMON = {
    "!important": "St's libcroco parser has no !important support",
    "@define-color": "not supported by Cinnamon's St CSS (GTK-only)",
    "@import": "not supported in cinnamon.css",
    "var(": "CSS custom properties are not supported by St",
    "backdrop-filter": "no such property in St; use 'background-blur: <int>'",
    "transition": "St has no transitions",
    "calc(": "not supported by St",
    "border-top-left-radius": "St calls it 'border-radius-topleft'",
    "border-top-right-radius": "St calls it 'border-radius-topright'",
    "border-bottom-left-radius": "St calls it 'border-radius-bottomleft'",
    "border-bottom-right-radius": "St calls it 'border-radius-bottomright'",
}
BANNED_IN_GTK = {
    "!important": "not valid in GTK CSS; it is dropped",
    "background-blur": "St-only property; GTK ignores it",
}
# alpha(r,g,b,a) is the SCSS helper from upstream themes; plain GTK CSS needs rgba()
GTK_ALPHA_RE = re.compile(r"(?<![\w-])alpha\(\s*\d")

DEAD_DIRS = {
    "metacity-1": "Muffin no longer parses metacity-theme-3.xml; window frames "
    "come from the GTK theme (window.ssd > decoration > headerbar). Delete this.",
}

CINNAMON_ALLOWLIST_PATH = "tools/upstream-selectors.txt"
# names checked by hand (see the file for the evidence lines) and merged in
MANUAL_ALLOWLIST_PATH = "tools/verified-selectors.txt"
# SCSS %placeholders from the default theme — they exist as class names at runtime
CORE_ONLY_OK = re.compile(r"^(?:appmenu|button|entry|grouped|dialog|osd|slider|menuitem|flat|large|smaller|title|caption|start)[_-]")


def strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def selectors_of(css: str) -> list[str]:
    """Top-level selector tokens of every rule (declarations ignored)."""
    out = []
    for m in re.finditer(r"(^|\})([^{}@]+)\{", css):
        chunk = m.group(2)
        if "@" in chunk:  # at-rule preamble (keyframes etc.)
            continue
        for part in chunk.split(","):
            part = part.strip()
            if not part or part in ("from", "to"):
                continue
            out.append(part)
    return out


def selector_atoms(sel: str) -> list[str]:
    """Bare names of the id/class atoms in a compound selector ('#panel' -> 'panel').

    The allowlist stores bare names because Cinnamon assigns an id and a class
    with the same string (set_name('panel') -> #panel, style_class 'panel' ->
    .panel), so matching on the name is what upstream actually guarantees.
    """
    return [a.lstrip(".#") for a in re.findall(r"[.#][A-Za-z][A-Za-z0-9_-]*", sel)]


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}")


# --------------------------------------------------------------------------- checks
def check_css(root: str, rel: str, rep: Report, allow: set[str] | None) -> None:
    path = os.path.join(root, rel)
    if not os.path.isfile(path):
        rep.err(rel, "missing")
        return
    raw = open(path, encoding="utf-8").read()
    css = strip_comments(raw)

    # structural
    depth = 0
    line = 1
    for ch in css:
        if ch == "\n":
            line += 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                rep.err(rel, f"unbalanced '}}' at line {line}")
                break
    if depth > 0:
        rep.err(rel, f"{depth} unclosed '{{' block(s)")

    banned = BANNED_IN_CINNAMON if "cinnamon/" in rel else BANNED_IN_GTK
    for token, why in banned.items():
        if token in css:
            # allow the word inside comments already stripped; report first hit
            ln = css[: css.index(token)].count("\n") + 1
            rep.err(rel, f"line {ln}: '{token}' — {why}")
    if "gtk-3.0" in rel or "gtk-4.0" in rel:
        for m in GTK_ALPHA_RE.finditer(css):
            ln = css[: m.start()].count("\n") + 1
            rep.err(rel, f"line {ln}: alpha(...) with numeric args — use rgba(r,g,b,a)")
        if re.search(r"(?m)^\s*\*\s*(?::[\w-]+)?\s*\{", css):
            rep.err(rel, "a bare '*' selector — global font/size overrides break "
                         "icon fonts and CSD menus; scope it to real nodes")

    # selector existence (cinnamon.css only, where an allowlist exists)
    if allow is not None and "cinnamon/" in rel:
        unknown = sorted(
            {
                atom
                for sel in selectors_of(css)
                for atom in selector_atoms(sel)
                if atom not in allow and not CORE_ONLY_OK.search(atom)
            }
        )
        if unknown:
            rep.warn(
                rel,
                "selector(s) not found in upstream Cinnamon/Mint-Y themes "
                f"(possibly inert): {', '.join(unknown)}",
            )


def check_index_theme(root: str, rep: Report) -> None:
    path = os.path.join(root, "theme/Iris/index.theme")
    if not os.path.isfile(path):
        rep.err("theme/Iris/index.theme", "missing")
        return
    text = open(path, encoding="utf-8").read()
    if "[X-GNOME-Metatheme]" not in text:
        rep.err("index.theme", "no [X-GNOME-Metatheme] group — cinnamon-settings will "
                               "not read GtkTheme/IconTheme from a [Desktop Entry] group")
    for key in ("GtkTheme", "ButtonLayout"):
        if not re.search(rf"^{key}=", text, re.M):
            rep.warn("index.theme", f"missing '{key}' key")


def check_dead_theme_parts(root: str, rep: Report) -> None:
    base = os.path.join(root, "theme/Iris")
    if not os.path.isdir(base):
        return
    for name, why in DEAD_DIRS.items():
        if os.path.exists(os.path.join(base, name)):
            rep.err(f"theme/Iris/{name}", why)


def check_keyfiles(root: str, rep: Report) -> None:
    for rel in ("sessions/iris.desktop", "sessions/iris-wayland.desktop"):
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            rep.err(rel, "missing")
            continue
        text = open(path, encoding="utf-8").read()
        for key in ("Name", "Exec", "Type"):
            if not re.search(rf"^{key}=", text, re.M):
                rep.err(rel, f"missing required key '{key}'")
        m = re.search(r"^Exec=(.+)$", text, re.M)
        if m:
            line = m.group(1).strip()
            # Either the upstream wrapper (cinnamon-session-cinnamon) or an
            # explicit --session <name> is correct; a bare `cinnamon-session`
            # with no --session is what produces a session with no components.
            if "cinnamon-session" in line and "--session" not in line \
                    and not line.rstrip().endswith("cinnamon-session-cinnamon"):
                rep.err(rel, "Exec starts cinnamon-session without --session <name>: "
                             "the component list is skipped (see data/xsessions in upstream)")
        dfv = shutil_which("desktop-file-validate")
        if dfv:
            r = subprocess.run([dfv, path], capture_output=True, text=True)
            if r.returncode != 0:
                rep.warn(rel, "desktop-file-validate: " + r.stdout.strip()[:400])

    for rel in ("sessions/iris.session", "sessions/iris-wayland.session"):
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            rep.err(rel, "missing")
            continue
        text = strip_comments_lines(open(path, encoding="utf-8").read())
        if "[Cinnamon Session]" not in text:
            rep.err(rel, "must use the [Cinnamon Session] group")
        if not re.search(r"^RequiredComponents=", text, re.M):
            rep.err(rel, "no RequiredComponents — the session would start nothing")
        dn = re.search(r"^DesktopName=(.+)$", text, re.M)
        if not dn:
            rep.err(rel, "no DesktopName")
        elif dn.group(1).strip() != "X-Cinnamon":
            rep.err(rel, f"DesktopName='{dn.group(1).strip()}' — OnlyShowIn=X-Cinnamon "
                         "autostart entries would be skipped and the session breaks")


def strip_comments_lines(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


GSETTINGS_SCHEMAS = {
    "org.cinnamon",
    "org.cinnamon.theme",
    "org.cinnamon.desktop.interface",
    "org.cinnamon.desktop.wm.preferences",
    "org.cinnamon.desktop.background",
    "org.cinnamon.desktop.notifications",
    "org.cinnamon.desktop.screensaver",
    "org.nemo.desktop",
}
# Keys that upstream Cinnamon does NOT define — this repo shipped several of
# them, and dconf happily stores garbage that nothing ever reads.
FORBIDDEN_KEYS = {
    ("org.cinnamon", "theme"),
    ("org.cinnamon", "panel-positions"),
    ("org.cinnamon", "panel-heights"),
    ("org.cinnamon.desktop.interface", "color-scheme"),
    ("org.cinnamon.desktop.interface", "document-font-name"),
    ("org.cinnamon.desktop.interface", "monospace-font-name"),
    ("org.cinnamon.desktop.background", "show-desktop-icons"),
    ("org.cinnamon.desktop.background", "show-desktop-icon-names"),
    ("org.cinnamon.desktop.notifications", "icon-size"),
}


def check_gsettings_profile(root: str, rep: Report) -> None:
    path = os.path.join(root, "config/gsettings/iris.gsettings")
    if not os.path.isfile(path):
        rep.err("config/gsettings/iris.gsettings", "missing")
        return
    seen = set()
    for i, raw in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) < 3:
            rep.err("iris.gsettings", f"line {i}: expected 3 tab-separated fields")
            continue
        schema, key, value = parts[0].strip(), parts[1].strip(), "\t".join(parts[2:]).strip()
        where = f"iris.gsettings:{i}"
        if schema not in GSETTINGS_SCHEMAS:
            rep.err(where, f"unknown schema '{schema}'")
        if (schema, key) in FORBIDDEN_KEYS:
            rep.err(where, f"'{schema} {key}' does not exist in Cinnamon (inert config)")
        if not value:
            rep.err(where, "empty value")
        if (schema, key) in seen:
            rep.err(where, f"duplicate entry for {schema} {key}")
        seen.add((schema, key))
        # applet uuid sanity: every uuid we name must exist in Cinnamon
        if key == "enabled-applets":
            for uuid in re.findall(r"'(panel\d+:[^']+)'", value):
                applet = uuid.split(":")[-1]
                if applet not in KNOWN_APPLETS:
                    rep.err(where, f"applet '{applet}' is not a Cinnamon applet")


KNOWN_APPLETS = {
    "a11y@cinnamon.org", "calendar@cinnamon.org", "cornerbar@cinnamon.org",
    "expo@cinnamon.org", "favorites@cinnamon.org", "grouped-window-list@cinnamon.org",
    "inhibit@cinnamon.org", "keyboard@cinnamon.org", "menu@cinnamon.org",
    "network@cinnamon.org", "nightlight@cinnamon.org", "notifications@cinnamon.org",
    "on-screen-keyboard@cinnamon.org", "panel-launchers@cinnamon.org",
    "power@cinnamon.org", "printers@cinnamon.org", "recent@cinnamon.org",
    "removable-drives@cinnamon.org", "scale@cinnamon.org", "separator@cinnamon.org",
    "settings@cinnamon.org", "show-desktop@cinnamon.org", "slideshow@cinnamon.org",
    "sound@cinnamon.org", "spacer@cinnamon.org", "systray@cinnamon.org",
    "trash@cinnamon.org", "user@cinnamon.org", "window-list@cinnamon.org",
    "windows-quick-list@cinnamon.org", "workspace-switcher@cinnamon.org",
    "xapp-status@cinnamon.org", "xrandr@cinnamon.org",
}

FORBIDDEN_PACKAGES = {
    "plymouth-theme-iris": "does not exist in any Debian suite",
    "nm-applet": "not a Debian package; install network-manager-gnome",
    "gpaste": "clipboard manager, not part of a themed desktop",
}


def check_packagelist(root: str, rep: Report) -> None:
    path = os.path.join(root, "config/package-lists/iris-core.list.chroot")
    if not os.path.isfile(path):
        rep.warn("config/package-lists/iris-core.list.chroot", "missing")
        return
    seen = set()
    for i, raw in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        where = f"iris-core.list.chroot:{i}"
        if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]+", line):
            rep.err(where, f"'{line}' is not a valid Debian package name")
        if line in FORBIDDEN_PACKAGES:
            rep.err(where, f"'{line}' — {FORBIDDEN_PACKAGES[line]}")
        if line in seen:
            rep.err(where, f"duplicate package '{line}'")
        seen.add(line)


def load_allowlist(root: str) -> set[str] | None:
    """Union of the generated upstream list and the hand-verified additions."""
    out: set[str] = set()
    found = False
    for rel in (CINNAMON_ALLOWLIST_PATH, MANUAL_ALLOWLIST_PATH):
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            continue
        found = True
        for line in open(path, encoding="utf-8"):
            line = line.split("#", 1)[0].strip()
            if line:
                out.add(line.lstrip(".#"))
    return out if found else None


def shutil_which(name: str):
    from shutil import which

    return which(name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = ap.parse_args()
    root = os.path.abspath(args.root)

    rep = Report()
    allow = load_allowlist(root)
    if allow is None:
        rep.warn(CINNAMON_ALLOWLIST_PATH, "allowlist missing — selector check disabled "
                                          "(run `make selectors`)")

    check_css(root, "theme/Iris/cinnamon/cinnamon.css", rep, allow)
    check_css(root, "theme/Iris/gtk-3.0/gtk.css", rep, allow)
    check_css(root, "theme/Iris/gtk-3.0/gtk-translucent.css", rep, allow)
    check_css(root, "theme/Iris/gtk-4.0/gtk.css", rep, allow)
    check_index_theme(root, rep)
    check_dead_theme_parts(root, rep)
    check_keyfiles(root, rep)
    check_gsettings_profile(root, rep)
    check_packagelist(root, rep)

    # shell scripts: syntax + (if available) shellcheck
    for dirpath, _dirs, files in os.walk(os.path.join(root, "scripts")):
        for f in sorted(files):
            if not (f.endswith(".sh") or f == "install.sh" or f == "uninstall.sh"):
                continue
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, root)
            r = subprocess.run(["bash", "-n", p], capture_output=True, text=True)
            if r.returncode:
                rep.err(rel, "bash syntax error: " + r.stderr.strip()[:300])
    if shutil_which("shellcheck"):
        scripts = [
            os.path.join(dp, f)
            for dp, _d, fs in os.walk(os.path.join(root, "scripts"))
            for f in fs
            if f.endswith(".sh")
        ]
        if scripts:
            r = subprocess.run(["shellcheck", *scripts], capture_output=True, text=True)
            if r.returncode:
                for ln in r.stdout.splitlines():
                    rep.warn("shellcheck", ln.strip())

    print(f"checked {root}")
    for m in rep.errors:
        print(f"  ERROR   {m}")
    for m in rep.warnings:
        print(f"  warning {m}")
    print(f"\n{len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
    if rep.errors:
        return 1
    if rep.warnings and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
