#!/usr/bin/env python3
"""Iris preview — render the theme in a browser, driven by the files in this repo.

    make preview            # then open the printed URL
    python3 tools/preview.py --port 8080

What this is: a *web* mock of the Cinnamon desktop (panel, menus, notifications,
the Settings app, windows) whose styling is generated at request time by parsing
theme/Iris/cinnamon/cinnamon.css and theme/Iris/gtk-3.0/gtk.css. No value is
hand-copied into the mock: edit the theme, reload, the preview changes. That is
the point — it makes the skin reviewable without a VM, and it makes "the CSS
names a rule that does not exist" impossible to hide, because the mapping tab
lists which rule produced which element.

What this is NOT: a GTK or St renderer. Real pixels differ — Pango hinting,
Clutter's blur and Muffin's frame clipping cannot be reproduced in a browser.
Two St-only properties have no web equivalent and are approximated, and every
approximation is listed in the Mapping tab:
  background-blur: N     -> backdrop-filter: blur(Npx)
  -st-vfade-offset: Npx  -> mask-image: linear-gradient(...)
Declarations with no translation are reported instead of being dropped silently.

Endpoints: /  /preview.css  /preview-base.css  /preview.js  /assets/wallpaper.png
             /api/report (mapping JSON)  /api/check (runs tools/check-theme.py)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CINNAMON_CSS = "theme/Iris/cinnamon/cinnamon.css"
GTK3_CSS = "theme/Iris/gtk-3.0/gtk.css"
PROFILE = "config/gsettings/iris.gsettings"
WALLPAPER = "wallpapers/iris-aluminium.png"

# Things the mock does differently from the real shell, on purpose. Listed in the
# mapping tab so nobody mistakes a mock convenience for a theme bug.
DEVIATIONS = [
    "`#t-main_stack` is shown as two columns. Real cinnamon-settings swaps one "
    "GtkStack page for another (`side_view_page` <-> `content_box_page`), so the "
    "sidebar is not a persistent pane — see docs/DESIGN.md §7.",
    "IconView tile gaps come from Cinnamon's Python (`set_item_width`, "
    "`column_spacing 18`), not from CSS, so the mock hard-codes a grid; the tile "
    "*style* is the theme's, the tile *metrics* are the shell's.",
    "`background-blur` is drawn with `backdrop-filter`. In Cinnamon it re-reads "
    "the scene each frame, so cost and edge behaviour differ; treat this as "
    "presence/absence, not performance.",
    "Window frames: Muffin clips `decoration` with the titlebar's radius in SSD "
    "mode. A browser cannot clip a top-level, so rounding is faked with "
    "`border-radius` + `overflow` on the same node.",
    "Fonts: the theme asks for Inter/Cantarell via Pango; the browser uses "
    "whatever it has. Metrics (and therefore padding decisions) shift a little.",
]


def profile_number(key: str, field: int, default: float = 0.0) -> float:
    """Pull a number out of the shipped gsettings profile (e.g. panel height)."""
    try:
        text = open(os.path.join(ROOT, PROFILE), encoding="utf-8").read()
    except OSError:
        return default
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 3 and parts[1].strip() == key:
            nums = re.findall(r"-?\d+(?:\.\d+)?", parts[2])
            if len(nums) > field:
                return float(nums[field])
    return default


# --------------------------------------------------------------------------
# CSS parsing
# --------------------------------------------------------------------------
_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def blank_comments(text: str) -> str:
    """Blank out comment bodies, keeping newlines so offsets still map to lines."""
    return _COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def parse_rules(text: str) -> list[dict]:
    """Return [{selectors, decls, line}] in file order."""
    body = blank_comments(text)
    out: list[dict] = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", body):
        head, inner = m.group(1).strip(), m.group(2)
        if "@" in head:
            continue  # @define-color and friends are handled separately
        decls = [(d.group(1).strip(), d.group(2).strip())
                 for d in re.finditer(r"([-\w]+)\s*:\s*([^;{}]+)", inner)]
        decls = [(p, v) for p, v in decls if not p.startswith("@")]
        if not decls:
            continue
        out.append({
            "selectors": [s.strip() for s in head.split(",") if s.strip()],
            "decls": decls,
            "line": body.count("\n", 0, m.start(1)) + 1,
        })
    return out


def parse_colors(text: str) -> dict[str, str]:
    return dict(re.findall(r"@define-color\s+([\w-]+)\s+([^;]+);", text))


def expand_tokens(value: str, colors: dict[str, str], depth: int = 0) -> str:
    if depth > 6:
        return value
    new = re.sub(r"@([\w-]+)", lambda m: colors.get(m.group(1), m.group(0)), value)
    return new if new == value else expand_tokens(new, colors, depth + 1)


# --------------------------------------------------------------------------
# numbers / units
# --------------------------------------------------------------------------
def _num(v: str) -> float:
    m = re.match(r"-?[\d.]+", v.strip())
    return float(m.group(0)) if m else 0.0


def _px(v: str) -> str:
    v = v.strip()
    if re.search(r"(px|pt|%|em|rem)$", v):
        return v
    return f"{_num(v):g}px"


def _vf(v: str) -> str:
    n = _px(v)
    return (f"linear-gradient(to bottom, transparent 0, black {n}, "
            f"black calc(100% - {n}), transparent 100%)")


def _hf(v: str) -> str:
    n = _px(v)
    return (f"linear-gradient(to right, transparent 0, black {n}, "
            f"black calc(100% - {n}), transparent 100%)")


def _blur(v: str) -> str:
    return f"blur({_px(v)})"


# --------------------------------------------------------------------------
# Selector translation: theme selector -> mock DOM selector
# --------------------------------------------------------------------------
# Pseudo-classes the browser understands directly; everything else (Cinnamon's
# :selected / :highlight / :dnd / St's :overview) is mirrored onto a class the
# mock can force, otherwise the state styling would silently disappear.
KEEP_PSEUDO = (":hover", ":focus", ":active", ":first-child", ":last-child",
               ":only-child")
STATE_CLASS = {
    ":checked": "is-checked",
    ":backdrop": "is-backdrop",
    ":selected": "is-selected",
    ":highlight": "is-highlight",
    ":dnd": "is-dnd",
    ":prelight": "is-hover",
    ":insensitive": "is-disabled",
    ":overview": "is-overview",
    ":alt-pressed": "is-alt",
    ":indeterminate": "is-indeterminate",
}
_CLASS_TOKEN = re.compile(r"\.([\w-]+)")


def translate_simple(part: str) -> tuple[str, bool]:
    """`.applet-box:checked` -> ('.t-applet-box.is-checked', True).

    Pseudo-classes are pulled out first so the "rename every class/element" step
    cannot mangle them (`:focus` becoming `:.t-focus` is invalid and would drop the
    whole rule in a browser). Returns usable=False for selectors whose nodes the
    mock does not build.
    """
    out = part.strip()
    held: list[str] = []

    def hold(m: re.Match) -> str:
        held.append(m.group(0))
        return f"\x00{len(held) - 1}\x00"

    out = re.sub(r":[\w-]+(?:\([^)]*\))?", hold, out)
    forced = []
    for state, cls in STATE_CLASS.items():
        plain = "\x00" + str(held.index(state)) + "\x00" if state in held else None
        if state in out or plain:
            out = out.replace(state, "").replace(plain or "\x00nope\x00", "")
            forced.append(cls)
    out = re.sub(r"#([\w-]+)", r"#t-\1", out)
    out = _CLASS_TOKEN.sub(r".t-\1", out)
    out = re.sub(r"(?<![\w.#-])([a-z][\w-]*)(?![\w-])", r".t-\1", out)
    # restore kept pseudos; drop the ones we turned into classes
    def restore(m: re.Match) -> str:
        token = m.group(0)
        raw = held[int(re.sub(r"[^0-9]", "", token))]
        return raw if raw in KEEP_PSEUDO else ""

    out = re.sub(r"\x00\d+\x00", restore, out)
    for cls in forced:
        out += "." + cls
    out = re.sub(r"\s*([>.])\s*", r" \1 ", out).strip()
    out = re.sub(r"\s+", " ", out).replace(" ", "").replace(">", " > ")
    return out, bool(out)


def translate_selector(sel: str) -> tuple[str, bool]:
    """Translate a possibly-descendant selector; CamelCase widget nodes are skipped."""
    if re.search(r"\b[A-Z][a-z]+[A-Z]\w*", sel):  # StScrollBar, StButton, CinnamonGenericContainer…
        return "", False
    parts = []
    for chunk in sel.split():
        translated, ok = translate_simple(chunk)
        if not ok:
            return "", False
        parts.append(translated)
    return " ".join(parts), True


# --------------------------------------------------------------------------
# Property translation
# --------------------------------------------------------------------------
COPY_PROPS_DOC = {
    "background-color", "background-image", "color", "border-radius", "border",
    "border-width", "border-color", "border-style", "box-shadow", "padding",
    "margin", "margin-left", "margin-right", "margin-top", "margin-bottom",
    "font-size", "font-weight", "font-style", "min-width", "min-height",
    "max-width", "max-height", "opacity", "text-shadow", "text-align",
    "border-top-width", "border-bottom-width", "border-left-width",
    "border-right-width", "border-top-color", "border-bottom-color",
    "border-left-color", "border-right-color", "border-top-left-radius",
    "border-top-right-radius", "border-bottom-left-radius",
    "border-bottom-right-radius", "letter-spacing",
}

APPROXIMATE = {
    "background-blur": ("backdrop-filter", _blur,
                        "St blurs the composited scene behind the actor; the browser "
                        "blurs what is behind the element. Good enough to judge the "
                        "look, not the cost."),
    "spacing": ("gap", _px, "St box spacing maps to flex gap."),
    "border-radius-topleft": ("border-top-left-radius", _px, ""),
    "border-radius-topright": ("border-top-right-radius", _px, ""),
    "border-radius-bottomleft": ("border-bottom-left-radius", _px, ""),
    "border-radius-bottomright": ("border-bottom-right-radius", _px, ""),
    "-st-vfade-offset": ("mask-image", _vf,
                         "St fades the top/bottom of a scroll view; emulated with a mask."),
    "-st-hfade-offset": ("mask-image", _hf, "same, horizontally"),
    "icon-size": ("--iris-icon-size", _px,
                  "shell icon size; the mock feeds it to its glyph boxes."),
}


class Gen:
    """Parses the theme and emits the mock stylesheet + the mapping report."""

    def __init__(self, opts: dict) -> None:
        self.opts = opts
        self.report: list[dict] = []
        self.untranslated: dict[str, list[str]] = {}
        self.skipped: dict[str, list[str]] = {}
        self.tokens: dict[str, str] = {}
        self.sources: dict[str, str] = {}
        self.rules: dict[str, list[dict]] = {}
        for name in (CINNAMON_CSS, GTK3_CSS):
            text = self.read(name)
            self.sources[name] = text
            self.tokens.update(parse_colors(text))
            self.rules[name] = parse_rules(text)

    @staticmethod
    def read(rel: str) -> str:
        try:
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""

    # -- knobs -------------------------------------------------------------
    def _tune(self, prop: str, value: str) -> str:
        o = self.opts
        if prop == "background-color" and o.get("alpha") is not None:
            alpha = float(o["alpha"])
            if "rgba(" in value:
                value = re.sub(r"rgba\(([^,]+),([^,]+),([^,]+),[\d.]+\)",
                               lambda m: f"rgba({m.group(1)},{m.group(2)},"
                                         f"{m.group(3)},{alpha:g})", value)
            elif "rgb(" in value:
                value = re.sub(r"rgb\(([^)]+)\)",
                               lambda m: f"rgba({m.group(1)},{alpha:g})", value)
        if prop.startswith("border-radius") and o.get("radius") is not None:
            scale = float(o["radius"])
            if "99" not in value:  # pill radii stay pills
                value = " ".join(f"{_num(p) * scale:g}px" for p in value.split())
        if prop == "background-blur":
            if o.get("blur") is not None:
                blur = float(o["blur"])
                return "__drop__" if blur <= 0 else f"{blur:g}"
        return value

    def decls_for(self, decls, source, line, sel):
        """Translate one rule's declarations into web declarations.

        Order matters: St-only names that happen to look like web properties
        (`spacing`, `border-radius-topleft`) must be caught by the approximation
        table before the "looks fine in a browser" branch, or the mock would emit
        a property the browser ignores and the value would be lost silently.
        """
        out = []
        for prop, value in decls:
            value = expand_tokens(value, self.tokens)
            tuned = self._tune(prop, value)
            if tuned == "__drop__":
                continue
            if prop in APPROXIMATE:
                web_prop, fn, note = APPROXIMATE[prop]
                try:
                    web_val = fn(tuned)
                except Exception:  # noqa: BLE001 - never kill the page over one value
                    web_val = tuned
                out.append((web_prop, web_val, note or f"approximated from `{prop}`"))
                if web_prop == "--iris-icon-size":
                    out.append(("--iris-glyph", web_val, "derived"))
            elif prop.startswith(("@", "-")):
                self.untranslated.setdefault(source, []).append(
                    f"<code>{prop}: {value}</code> in <code>{sel}</code> (line {line})"
                    " — GTK/St-only, no web equivalent")
            else:
                out.append((prop, tuned, ""))
        return out

    def css(self) -> str:
        self.report = []
        height = profile_number("panels-height", 1, 44)
        chunks = [
            "/* GENERATED by tools/preview.py from the theme files — do not edit. */",
            f":root {{ --iris-panel-height: {height:g}px; "
            "/* from config/gsettings/iris.gsettings panels-height */ }",
        ]
        for source in (CINNAMON_CSS, GTK3_CSS):
            for rule in self.rules[source]:
                mock_sels = []
                for sel in rule["selectors"]:
                    translated, ok = translate_selector(sel)
                    if not ok or not translated:
                        self.skipped.setdefault(source, []).append(
                            f"<code>{sel}</code> (line {rule['line']}) — no such node in "
                            "the mock (widget-class selectors like "
                            "<code>StScrollBar StButton</code> are not built)")
                        continue
                    mock_sels.append(translated)
                    self.report.append({
                        "source": source, "line": rule["line"], "selector": sel,
                        "mock": translated,
                        "props": [f"{p}: {v}" for p, v in rule["decls"]],
                    })
                if not mock_sels:
                    continue
                pairs = self.decls_for(rule["decls"], source, rule["line"],
                                       rule["selectors"][0])
                if not pairs:
                    continue
                body = "".join(f"  {p}: {v};\n" for p, v, _ in pairs)
                name = source.split("/")[-2] + "/" + source.split("/")[-1]
                chunks.append(f"/* {name}:{rule['line']}  <-  "
                              f"{', '.join(rule['selectors'])} */")
                chunks.append(",\n".join(mock_sels) + " {\n" + body + "}\n")
        return "\n".join(chunks)


# --------------------------------------------------------------------------
# The mock desktop
# --------------------------------------------------------------------------
def panel_html(gen: Gen) -> str:
    side = gen.opts.get("panel", "bottom")
    tiles = "".join(
        f'<div class="t-applet-box t-window-list-box">'
        f'<div class="t-window-list-item-box {extra}">'
        f'<span class="glyph">{"▤▣▦▨"[i % 4]}</span>'
        f'<span class="t-label window-list-label">{name}</span></div></div>'
        for i, (name, extra) in enumerate([
            ("Files", ""), ("Settings", "is-checked"),
            ("Mozilla Firefox", ""), ("Text Editor", ""),
        ]))
    tray = "".join(
        f'<div class="t-applet-box t-systray-box"><span class="glyph t-applet-icon">{g}</span></div>'
        for g in ["⬉", "◍", "⌁", "▮"])
    return f"""
<div class="t-panel t-panel-{side}" id="t-panel">
  <div class="t-panel-left" id="t-panelLeft">
    <div class="t-applet-box t-panel-menu-button">
      <span class="glyph">◉</span><span class="t-label">Iris</span>
    </div>
    <div class="t-applet-box"><span class="glyph t-applet-icon">▤</span></div>
    <div class="t-applet-box"><span class="glyph t-applet-icon">◍</span></div>
  </div>
  <div class="t-panel-center" id="t-panelCenter">{tiles}</div>
  <div class="t-panel-right" id="t-panelRight">
    {tray}
    <div class="t-applet-separator"><span class="t-applet-separator-line"></span></div>
    <div class="t-applet-box t-clock-box">
      <div class="t-label clock-time">12:30</div>
      <div class="t-label clock-date">Oct 29, 2026</div>
    </div>
  </div>
</div>"""


def window_html(title, body, cls="", backdrop=False, icon="▤"):
    state = " is-backdrop" if backdrop else ""
    return f"""
<div class="t-window {cls}">
  <div class="t-decoration{state}">
    <header class="t-headerbar t-titlebar">
      <span class="glyph win-icon">{icon}</span>
      <span class="t-label title">{title}</span>
      <span class="spacer"></span>
      <span class="t-button t-titlebutton win-min">–</span>
      <span class="t-button t-titlebutton win-max">▢</span>
      <span class="t-button t-titlebutton win-close">✕</span>
    </header>
    <div class="content">{body}</div>
  </div>
</div>"""


def settings_body(gen: Gen) -> str:
    tiles = "".join(
        f'<div class="t-iconview-item {sel}"><span class="glyph">{g}</span>'
        f'<span class="t-label">{name}</span></div>'
        for g, name, sel in [
            ("⬉", "Network", ""), ("◍", "Bluetooth", ""), ("⌁", "Connected devices", ""),
            ("☻", "Account", ""), ("▣", "Device", "is-selected"),
            ("✦", "Personalizations", ""), ("⌕", "Search and Assistant", ""),
            ("⛨", "Security and Privacy", ""), ("▦", "Apps", ""), ("⚙", "Advanced", ""),
        ])
    rows = ""
    for label, desc, control in [
        ("Pin to shelf", "Keep this app in the taskbar", "switch"),
        ("Notifications", "Allow badges and popups", "switch-on"),
        ("Location", "Allowed - while in use", "select"),
        ("Camera", "Blocked by policy", "select"),
        ("Storage", "128 GB of 256 GB used", "static"),
    ]:
        if control.startswith("switch"):
            on = " is-checked" if control == "switch-on" else ""
            ctl = f'<div class="t-switch{on}"><div class="t-slider"></div></div>'
        elif control == "select":
            ctl = '<div class="t-entry t-select"><span class="t-label">on device</span>' \
                  '<span class="glyph">⌄</span></div>'
        else:
            ctl = '<div class="t-label dim">read-only</div>'
        rows += f"""
        <div class="t-row">
          <div class="row-text"><span class="t-label"><b>{label}</b></span>
            <span class="t-label dim">{desc}</span></div>
          {ctl}
        </div>
        <div class="t-separator"></div>"""
    return f"""
<div class="t-toolbar" id="t-top_bar">
  <div class="t-button" id="t-button_back"><span class="glyph">←</span></div>
  <div class="t-entry" id="t-search_box" tabindex="0">
    <span class="glyph">⌕</span><span class="t-label dim">Search apps</span>
    <span class="spacer"></span><span class="glyph">✕</span>
  </div>
  <div class="t-stackswitcher" id="t-stack_switcher">
    <div class="t-button is-checked">Personalizations</div>
    <div class="t-button">Search and Assistant</div>
    <div class="t-button">Security and Privacy</div>
  </div>
</div>
<div class="t-stack" id="t-main_stack">
  <div class="t-scrolledwindow t-cs-category-view t-view" id="t-side_view_sw">
    <div class="t-box t-vertical" id="t-category_box">
      <div class="t-box t-horizontal cat-head">
        <span class="glyph cat-icon">✦</span>
        <span class="t-label cat-title">Personalizations</span>
      </div>
      <div class="t-separator"></div>
      <div class="t-iconview">{tiles}</div>
    </div>
  </div>
  <div class="t-scrolledwindow" id="t-content_box_sw">
    <div class="t-box t-vertical" id="t-content_box">
      <div class="t-frame" id="t-c_box"><div class="t-box t-vertical">{rows}</div></div>
      <div class="t-frame">
        <div class="t-box t-vertical">
          <div class="t-row"><span class="t-label">Open supported links</span>
            <div class="t-switch is-checked"><div class="t-slider"></div></div></div>
        </div>
      </div>
    </div>
  </div>
</div>"""


def files_body() -> str:
    items = "".join(
        f'<div class="t-row t-list-row"><span class="glyph">{"▤▦▣▧▩"[i % 5]}</span>'
        f'<span class="t-label">{n}</span><span class="spacer"></span>'
        f'<span class="t-label dim">{s}</span></div>'
        for i, (n, s) in enumerate([
            ("Aluminium", "folder"), ("Screenshot 2026-10-29.png", "2.1 MB"),
            ("notes.md", "1 KB"), ("Debian-Iris", "folder"),
            ("iris-theme_0.2.0_all.deb", "1.0 MB"), ("wallpaper.jpg", "880 KB"),
        ]))
    return (
        '<div class="t-toolbar nemo-bar"><div class="t-button">←</div>'
        '<div class="t-button">→</div>'
        '<div class="t-entry path"><span class="t-label">/home/user/Aluminium</span></div></div>'
        f'<div class="t-list">{items}</div>'
        '<div class="t-popup-menu" id="t-nemo-menu">'
        '<div class="t-popup-menu-item is-selected"><span class="t-label">Open</span></div>'
        '<div class="t-popup-menu-item"><span class="t-label">Open with Files</span></div>'
        '<div class="t-popup-menu-item"><span class="t-label">Copy</span></div>'
        '<div class="t-popup-menu-item"><span class="t-label">Move to Trash</span></div>'
        '<div class="t-separator popup-sep"></div>'
        '<div class="t-popup-menu-item"><span class="t-label">Properties</span></div>'
        '</div>')


def calendar_body() -> str:
    heads = "".join(f'<div class="t-calendar-day-heading">{h}</div>' for h in "MTWTFSS")
    days = "".join(
        f'<div class="t-calendar-day-base {cls}">{d}</div>'
        for d, cls in [(str(i), "t-calendar-other-month-day" if i > 29 else
                        "t-calendar-today" if i == 29 else "t-calendar-work-day")
                       for i in range(1, 35)])
    return (f'<div class="t-popup-menu calendar-menu">'
            f'<div class="t-calendar-main-box">'
            f'<div class="t-calendar-month-label"><span>October 2026</span>'
            f'<div><span class="t-button flat">‹</span>'
            f'<span class="t-button flat">›</span></div></div>'
            f'<div class="t-calendar">{heads}{days}</div></div>'
            f'<div class="t-separator"></div>'
            f'<div class="t-sound-player">'
            f'<div class="t-albumart-widget"><span class="glyph">♫</span></div>'
            f'<div class="player-text"><div class="t-label">Internal Keyboard</div>'
            f'<div class="t-label dim">Volume 42%</div></div>'
            f'<div class="t-progress"><div class="t-progress-box"></div></div></div></div>')


def notification_html() -> str:
    return """
<div class="t-notification" id="t-notification">
  <div class="notif-icon"><span class="glyph">◍</span></div>
  <div class="notif-body" id="t-notification-body">
    <div class="t-label notif-title">Update Manager</div>
    <div class="t-label notif-text">12 updates available. The Iris package list was
      checked against Debian 13 (trixie).</div>
    <div class="t-button notif-action">Install updates</div>
  </div>
  <div class="t-button flat notif-close">✕</div>
</div>"""


def osd_html() -> str:
    return """
<div class="t-info-osd"><span class="glyph">♊</span><span class="t-label">Volume 42%</span></div>
<div class="t-altTabPopup">
  <div class="t-switcher-list">
    <div class="t-item-box is-selected"><span class="glyph">▤</span>
      <span class="t-label">Settings</span></div>
    <div class="t-item-box"><span class="glyph">◍</span><span class="t-label">Firefox</span></div>
    <div class="t-item-box"><span class="glyph">▦</span><span class="t-label">Files</span></div>
  </div>
</div>"""


def menu_html() -> str:
    cats = "".join(f'<div class="t-popup-menu-item {c}"><span class="t-label">{n}</span></div>'
                   for n, c in [("Places", ""), ("Recent", ""), ("Favorites", "is-selected"),
                                ("All apps", "")])
    apps = "".join(f'<div class="t-app-well"><span class="glyph">{g}</span>'
                   f'<span class="t-label">{n}</span></div>'
                   for g, n in [("", "System Settings"), ("", "Files"), ("", "Trash"),
                                ("⎙", "Printers"), ("⛨", "Firewall"), ("⏻", "Power off")])
    return f"""
<div class="t-popup-menu popup-menu" id="t-menu">
  <div class="t-entry" id="t-menu-search-entry">
    <span class="glyph">⌕</span><span class="t-label dim">Type here to search…</span>
  </div>
  <div class="menu-cols">
    <div class="menu-cats">{cats}</div>
    <div class="menu-apps">{apps}</div>
  </div>
  <div class="t-separator popup-sep"></div>
  <div class="menu-footer">
    <div class="t-button flat">⚐ Favorites</div>
    <div class="t-button flat">⛭ Settings</div>
    <div class="t-button flat">⏻ Power</div>
  </div>
</div>"""


def mapping_html(gen: Gen) -> str:
    rows = "".join(
        "<tr><td><code>{short}:{line}</code></td><td><code>{sel}</code></td>"
        "<td><code>{mock}</code></td><td class=props>{props}</td></tr>".format(
            short=item["source"].split("/")[-1], line=item["line"],
            sel=esc(item["selector"]), mock=esc(item["mock"]),
            props="<br>".join(f"<code>{esc(p)}</code>" for p in item["props"]))
        for item in gen.report)
    untr = "".join(f"<li><code>{src.split('/')[-1]}</code> — {line}</li>"
                   for src, items in gen.untranslated.items() for line in items)
    skip = "".join(f"<li><code>{src.split('/')[-1]}</code> — {line}</li>"
                   for src, items in gen.skipped.items() for line in items)
    approx = "".join(
        f"<li><code>{k}</code> → <code>{APPROXIMATE[k][0]}</code>"
        f"{': ' + APPROXIMATE[k][2] if APPROXIMATE[k][2] else ''}</li>"
        for k in sorted(APPROXIMATE))
    deviations = "".join(f"<li>{d}</li>" for d in DEVIATIONS)
    swatches = "".join(
        f'<div class="sw"><i style="background:{v}"></i><code>@{k}</code> <b>{v}</b></div>'
        for k, v in gen.tokens.items())
    n_un, n_skip = sum(len(v) for v in gen.untranslated.values()), \
        sum(len(v) for v in gen.skipped.values())
    return f"""
<section class="doc">
  <h2>Mapping — theme rule → mock element</h2>
  <p class="lead">{len(gen.report)} theme rules drive the mock, in file order. If a
  selector you expected is missing, the mock simply has no node for it — listed below,
  not hidden.</p>
  <table class="map"><thead><tr><th>rule</th><th>selector in theme file</th>
  <th>mock node</th><th>declarations</th></tr></thead><tbody>{rows}</tbody></table>

  <h2>Approximated on purpose</h2><ul>{approx}</ul>

  <h2>Mock deviations (read before judging)</h2>
  <ul class="deviations">{deviations}</ul>

  <h2>Not translated ({n_un})</h2>
  <p class="lead">Present in the theme, no web equivalent in this mock. In a real
  Cinnamon/GTK session these do apply.</p><ul>{untr or '<li>none</li>'}</ul>

  <h2>No mock node ({n_skip})</h2>
  <ul>{skip or '<li>none</li>'}</ul>

  <h2>Colour tokens from <code>@define-color</code></h2>
  <div class="swatches">{swatches}</div>
</section>"""


def esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def source_html(gen: Gen) -> str:
    blocks = []
    for src in (CINNAMON_CSS, GTK3_CSS):
        mapped = {r["line"] for r in gen.report if r["source"] == src}
        lines = "".join(
            f'<li class="{"hit" if i in mapped else ""}"><span class="no">{i}</span>'
            f"<code>{esc(line) or ' '}</code></li>"
            for i, line in enumerate(gen.sources[src].splitlines(), 1))
        blocks.append(f"<h2>{src} <small>{len(gen.sources[src].splitlines())} lines · "
                      f"{len(mapped)} of them style the mock</small></h2>"
                      f"<ol class='src'>{lines}</ol>")
    return "<section class='doc'>" + "".join(blocks) + "</section>"


def q(opts: dict, **over) -> str:
    merged = {k: v for k, v in opts.items() if not isinstance(v, bool)}
    merged.update(over)
    for key in ("dim", "grid", "labels"):
        if opts.get(key):
            merged[key] = "1"
    out = []
    for k, v in merged.items():
        out.append(f"{k}={v:g}" if isinstance(v, float) else f"{k}={v}")
    return "&".join(out)


def controls_html(gen: Gen) -> str:
    o = gen.opts

    def rng(name, label, lo, hi, step, cur, unit=""):
        val = "" if cur is None else f"{cur:g}"
        shown = "theme default" if cur is None else f"{cur:g}{unit}"
        return (f'<label>{label}<input type="range" data-knob="{name}" min="{lo}" '
                f'max="{hi}" step="{step}" value="{val}" placeholder="default">'
                f"<output>{shown}</output></label>")

    sel = "".join(
        f'<option value="{v}"{" selected" if v == o.get("panel", "bottom") else ""}>{t}</option>'
        for v, t in [("bottom", "bottom (floating pill)"), ("top", "top"),
                     ("left", "left / vertical"), ("right", "right / vertical")])
    tab = o.get("tab", "desk")
    checks = "".join(
        f'<label><input type="checkbox" data-flag="{k}"{" checked" if o.get(k) else ""}> '
        f"{t}</label>"
        for k, t in [("dim", "unfocused windows"), ("grid", "alignment grid"),
                     ("labels", "node labels")])
    return f"""
<aside class="controls">
  <div class="ctl-head"><b>Iris preview</b><small>rendered from the repo files</small></div>
  <label>panel position<select data-knob="panel">{sel}</select></label>
  {rng("blur", "background-blur", 0, 30, 1, o.get("blur"), "px")}
  {rng("alpha", "surface alpha", 20, 100, 1, o.get("alpha"), "%")}
  {rng("radius", "radius scale", 0, 200, 5, o.get("radius"), "%")}
  <div class="toggles">{checks}</div>
  <nav class="tabs">
    <a class="{'on' if tab == 'desk' else ''}" href="?{q(o, tab='desk')}">desktop</a>
    <a class="{'on' if tab == 'map' else ''}" href="?{q(o, tab='map')}">mapping</a>
    <a class="{'on' if tab == 'src' else ''}" href="?{q(o, tab='src')}">source</a>
  </nav>
  <p class="warn"><b>Web mock, not a GTK/St render.</b> Font hinting, Clutter's blur
  and Muffin's frame clipping differ. Judge layout, colour, radius and hierarchy here;
  judge the feel on a real session. <a href="/api/check" target="_blank">run
  tools/check-theme.py</a></p>
</aside>"""


def page(gen: Gen) -> str:
    o = gen.opts
    body_cls = " ".join(c for c in ("dim", "grid", "labels") if o.get(c))
    tab = o.get("tab", "desk")
    if tab == "map":
        main = mapping_html(gen)
    elif tab == "src":
        main = source_html(gen)
    else:
        cal = calendar_body()
        main = f"""
<div class="desk {body_cls}">
  <div class="wallpaper"><img src="/assets/wallpaper.png" alt=""></div>
  {window_html("Aluminium — Internal SSD", files_body(), "win-files", o.get("dim"), "")}
  {window_html("Settings", settings_body(gen), "win-settings", False, "⚙")}
  {window_html("Text Editor — DESIGN.md",
               "<div class='t-textview'><div class='t-row'><span class='t-label'>"
               "## Tokens</span></div><div class='t-row'><span class='t-label dim'>"
               "accent #4c7fd0 · radius 14px · surface #f7f8fa</span></div></div>",
               "win-editor", o.get("dim"), "▤")}
  {menu_html()}
  <div class="cal-anchor">{cal}</div>
  {notification_html()}
  {osd_html()}
  {panel_html(gen)}
</div>"""
    return (f"<!doctype html><html lang=id><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>Iris preview</title>"
            f"<link rel=stylesheet href='/preview-base.css'>"
            f"<link rel=stylesheet href='/preview.css'>"
            f"</head><body class='theme-root {body_cls}' data-tab='{tab}'>"
            f"{main}{controls_html(gen)}<script src='/preview.js'></script></body></html>")


# --------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------
def parse_opts(qs: str) -> dict:
    o: dict = {}
    for k, vals in urllib.parse.parse_qs(qs).items():
        v = vals[-1]
        if k in ("blur", "radius", "alpha"):
            try:
                num = float(v)
            except ValueError:
                continue
            if k == "alpha":
                o[k] = num / 100.0
            elif k == "radius":
                o[k] = num / 100.0
            else:
                o[k] = num
        elif v in ("1", "on", "true"):
            o[k] = True
        else:
            o[k] = v
    return o


JS = r"""
// The knobs only ever change the query string; the server regenerates the CSS by
// re-parsing the theme files, so there is no second source of truth to drift.
const q = new URLSearchParams(location.search);
const go = () => { location.search = q.toString(); };
document.querySelectorAll('[data-knob]').forEach(el => {
  const key = el.dataset.knob;
  if (el.type === 'range') {
    const out = el.parentElement.querySelector('output');
    const unit = key === 'blur' ? 'px' : (key === 'radius' || key === 'alpha') ? '%' : '';
    el.addEventListener('input', () => {
      const v = Number(el.value);
      out.textContent = (key === 'blur' && v === 0) ? 'off' : v + unit;
      q.set(key, el.value);
    });
    el.addEventListener('change', go);
  } else if (el.tagName === 'SELECT') {
    el.addEventListener('change', () => { q.set(key, el.value); go(); });
  }
});
// "node labels" mode: annotate every mock element with the theme node it stands
// for, derived from its own t-* classes so it can never drift from the markup.
if (location.search.includes('labels=1')) {
  document.querySelectorAll('[class*="t-"]').forEach(el => {
    const names = [...el.classList].filter(c => c.startsWith('t-')).slice(0, 3);
    if (names.length) el.setAttribute('data-node', names.map(n => n.slice(2)).join('.'));
  });
}
// Clicking a mock control toggles the state class the theme styles
// (.is-selected / .is-checked), i.e. the preview reacts to the same CSS a real
// Cinnamon session would apply for that state.
const CLICKABLE = '.t-iconview-item, .t-switch, .t-stackswitcher .t-button, '
                + '.t-applet-box, .t-popup-menu-item, .t-calendar-day-base';
document.addEventListener('click', ev => {
  const el = ev.target.closest(CLICKABLE);
  if (!el || el.closest('.controls')) return;
  const exclusive = el.matches('.t-iconview-item, .t-popup-menu-item, .t-stackswitcher .t-button')
    ? 'is-selected' : null;
  if (el.matches('.t-switch')) { el.classList.toggle('is-checked'); return; }
  if (exclusive && el.classList.contains(exclusive)) { el.classList.remove(exclusive); return; }
  if (exclusive) {
    [...el.parentElement.children].forEach(sib => sib.classList.remove(exclusive));
    el.classList.add(exclusive);
    return;
  }
  el.classList.toggle('is-checked');
});
document.querySelectorAll('[data-flag]').forEach(el => {
  el.addEventListener('change', () => {
    el.checked ? q.set(el.dataset.flag, '1') : q.delete(el.dataset.flag);
    go();
  });
});
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "IrisPreview/1.0"

    def _send(self, code: int, ctype: str, data: bytes) -> None:
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_HEAD(self) -> None:  # noqa: N802
        self._send(200, "text/html; charset=utf-8", b"")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        opts = parse_opts(parsed.query)
        path = parsed.path.rstrip("/") or "/"
        if path in ("/", "/index.html"):
            try:
                gen = Gen(opts)
                gen.css()  # fills gen.report, which the mapping/source tabs read
                html = page(gen)
            except Exception as exc:  # noqa: BLE001 - show it, do not drop the socket
                html = (f"<pre>preview generator bug, not a theme bug:\n\n"
                        f"{exc!r}\n\nfix tools/preview.py and reload.</pre>")
            self._send(200, "text/html; charset=utf-8", html.encode())
        elif path == "/preview.css":
            try:
                css = Gen(opts).css()
            except Exception as exc:  # noqa: BLE001
                css = f"/* preview generator failed: {exc!r} */"
            self._send(200, "text/css; charset=utf-8", css.encode())
        elif path == "/preview-base.css":
            data = open(os.path.join(ROOT, "tools", "preview-base.css"), "rb").read()
            self._send(200, "text/css; charset=utf-8", data)
        elif path == "/preview.js":
            self._send(200, "application/javascript; charset=utf-8", JS.encode())
        elif path == "/assets/wallpaper.png":
            try:
                self._send(200, "image/png", open(os.path.join(ROOT, WALLPAPER), "rb").read())
            except OSError:
                self._send(404, "text/plain", b"wallpapers/iris-aluminium.png not found")
        elif path == "/api/report":
            gen = Gen(opts)
            gen.css()
            self._send(200, "application/json; charset=utf-8",
                       json.dumps({"rules": gen.report,
                                   "untranslated": gen.untranslated,
                                   "skipped": gen.skipped}, indent=1).encode())
        elif path == "/api/check":
            proc = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check-theme.py")],
                                  capture_output=True, text=True, cwd=ROOT)
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-60:]
            text = f"tools/check-theme.py -> exit={proc.returncode}\n\n" + "\n".join(tail)
            self._send(200, "text/plain; charset=utf-8", text.encode())
        else:
            self._send(404, "text/plain; charset=utf-8",
                       b"endpoints: /  /preview.css  /preview-base.css  /preview.js\n"
                       b"           /assets/wallpaper.png  /api/report  /api/check\n")

    def log_message(self, fmt: str, *args) -> None:
        if "--verbose" in sys.argv:
            super().log_message(fmt, *args)


def main() -> int:
    ap = argparse.ArgumentParser(description="web preview of the Iris theme")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--print", choices=["css", "html", "report"],
                    help="render once to stdout and exit (no server)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.print:
        gen = Gen({})
        if args.print == "css":
            print(gen.css())
        elif args.print == "report":
            gen.css()
            print(json.dumps({"rules": gen.report, "untranslated": gen.untranslated,
                              "skipped": gen.skipped}, indent=1))
        else:
            gen.css()
            print(page(gen))
        return 0

    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Iris preview on http://{args.host}:{args.port}/ "
          f"(parsing {CINNAMON_CSS} + {GTK3_CSS})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
