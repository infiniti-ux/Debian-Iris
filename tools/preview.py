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
WALLPAPER = "wallpapers/iris-aluminium-dark.png"

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
        head, inner = m.group(1), m.group(2)
        # Top-level statements (`@define-color …;`) sit between blocks and end in `;`.
        # Only the text after the last one can be a selector; without this the first
        # rule after the token block is eaten together with the `@define-color` head.
        if ";" in head:
            head = head.rsplit(";", 1)[-1]
        head = head.strip()
        if "@" in head:
            continue  # @media / @keyframes blocks are not part of the mock
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
# `:hover` is left to the browser - hovering the mock shows the real rule.
# `:focus` / `:active` become classes (see STATE_CLASS) because a `<div>` does not
# take focus or hold a press the way a GTK widget does; the preview's JS mirrors the
# events back onto those classes, so both the static markup and the interaction work.
KEEP_PSEUDO = (":hover", ":first-child", ":last-child", ":only-child")
STATE_CLASS = {
    ":checked": "is-checked",
    ":focus": "is-focused",
    ":active": "is-active",
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

    css_text = ""
    dead: list[str] = []
    autofill: tuple[str, int] = ("", 0)

    def css(self) -> str:
        self.css_text = self._css()
        return self.css_text

    def _css(self) -> str:
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
                    # GtkIconView/GtkTreeView/GtkFlowBox draw their item state on the
                    # view's own style context, so `iconview:selected` means "a selected
                    # item". The mock marks the item, not the view: add that variant or
                    # selection styling would look absent.
                    if re.search(r"iconview|treeview|flowbox", sel) and ".is-" in translated:
                        mock_sels.append(translated.replace(".is-", " .is-", 1))
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
    """The panel, using the class names the theme actually styles.

    Layout mirrors the rice: menu button + separator + launchers + window list,
    all centered; the side zones stay empty. The tray, spacer and clock are NOT
    here — in the rice they live on the top bar, and in the mock they are covered
    by the topbar strip below plus the Components tab, so dropping them costs no
    audit coverage. Node names follow cinnamon's own stylesheet
    (tools/upstream-selectors.txt). `hl` and `dnd` are the highlight and drag
    states the real panel only shows while the pointer is on it - exposed as
    knobs so that styling can be reviewed instead of guessed at.
    """
    side = gen.opts.get("panel", "bottom")
    hl = " is-highlight" if gen.opts.get("hl") else ""
    dnd = " is-dnd" if gen.opts.get("dnd") else ""
    vertical = side in ("left", "right")

    launchers = "".join(
        f'<div class="t-launcher"><div class="t-applet-box">'
        f'<span class="glyph t-applet-icon">{g}</span></div></div>'
        for g in ["🗔", "🗑", "🌐"])
    tiles = "".join(
        f'<div class="t-window-list-item-box{ " " + extra if extra else ""}">'
        f'<span class="glyph t-applet-icon">{"▤▣▦▨"[i % 4]}</span>'
        f'<span class="t-window-list-item-label window-list-label">{name}</span></div>'
        for i, (name, extra) in enumerate([
            ("Files", ""), ("Settings", "is-focused"),
            ("Mozilla Firefox", "is-urgent"), ("Text Editor", ""),
        ]))
    corner = ('<div class="t-panel-corner"></div>' if not vertical else
              '<div class="t-panel-corner t-panel-corner-left"></div>')
    # The rice runs TWO panels: a fixed dark top bar (clock left, tray right) plus
    # the main taskbar. The desk shows both, so the .panel-top rules land on a real
    # node instead of an auto-demo — except under ?panel=top, where the main panel
    # already is the top bar.
    topbar = "" if side == "top" else """
<div class="t-panel t-panel-top rice-topbar" id="t-topbar">
  <div class="t-panel-left" id="t-topbarLeft">
    <div class="t-applet-box t-clock-box">
      <div class="t-clock-widget">
        <div class="t-clock-time-label clock-time">7:14</div>
        <div class="t-clock-date-label clock-date">Mon, May 11</div>
      </div>
    </div>
  </div>
  <div class="t-panel-center"></div>
  <div class="t-panel-right" id="t-topbarRight">
    <div class="t-systray"><div class="t-applet-box"><span class="glyph t-system-status-icon t-applet-icon">◍</span></div></div>
    <div class="t-applet-box"><span class="glyph t-applet-icon">⌁</span><span class="t-applet-label">63%</span></div>
    <div class="t-applet-separator"><span class="t-applet-separator-line"></span></div>
  </div>
</div>"""
    return f"""
<div class="t-panel t-panel-{side}{hl}" id="t-panel">
  <div class="t-panel-left{dnd}" id="t-panelLeft">
    {corner}
  </div>
  <div class="t-panel-center{dnd}" id="t-panelCenter">
    <div class="t-applet-box t-panel-menu-button">
      <span class="glyph t-applet-icon">◉</span>
    </div>
    <div class="t-applet-separator"><span class="t-applet-separator-line"></span></div>
    <div class="t-panel-launchers">{launchers}</div>
    <div class="t-window-list">{tiles}</div>
  </div>
  <div class="t-panel-right{dnd}" id="t-panelRight">
    {corner}
  </div>
</div>{topbar}"""


def window_html(title, body, cls="", backdrop=False, icon="\u25a4", subtitle="",
                extra=""):
    """A window the way Muffin decorates a client-side-decoration window.

    `window.ssd` > `decoration` > `headerbar.titlebar` with `label.title` /
    `label.subtitle` / `button.titlebutton` is exactly what the theme targets, so
    the desktop titlebar is drawn by the same rules a real app would hit - not by
    scaffolding. `extra` can add `default-decoration` or `tiled` to show those rules.
    """
    state = " is-backdrop" if backdrop else ""
    buttons = "".join(
        f'<span class="t-button t-titlebutton win-{n}">{g}</span>'
        for g, n in [("\u2013", "min"), ("\u25a2", "max"), ("\u2715", "close")])
    sub = f'<span class="t-subtitle">{subtitle}</span>' if subtitle else ""
    return f"""
<div class="t-window t-ssd{ " t-tiled" if "tiled" in extra else ""} {cls}">
  <div class="t-decoration{state}">
    <header class="t-headerbar t-titlebar{state}{ " " + extra if extra else ""}">
      <span class="glyph win-icon">{icon}</span>
      <span class="t-title">{title}</span>{sub}
      <span class="spacer"></span>
      <div class="t-windowhandle"><div class="t-box t-titlebar-buttons">{buttons}</div></div>
    </header>
    <div class="content">{body}</div>
  </div>
</div>"""


def settings_body(gen: Gen) -> str:
    """Cinnamon Settings, mirroring cinnamon-settings.ui.

    top_bar > header_stack > (hbox2 > search_box) + (box2 > button_back,
    stack_switcher); main_stack flips between side_view (category_box) and the
    module page (content_box > c_box). The mock shows both panes at once because
    a browser cannot swap stack pages on click - stated as a deviation.
    """
    backdrop = " is-backdrop" if gen.opts.get("dim") else ""
    categories = (
        ("Preferences", "⚙", [("Appearance", 1), ("Themes", 0), ("Applets", 0),
                              ("Desklets", 0), ("Effects", 0), ("General", 0)]),
        ("Administration", "🛡", [("User Accounts", 0), ("Login Window", 0),
                                 ("System Info", 0)]),
    )
    cats = ""
    for title, glyph, items in categories:
        head = (f'<div class="t-box"><span class="t-image glyph">{glyph}</span>'
                f'<span class="t-label">{title}</span></div>')
        tiles = "".join(
            f'<div class="t-iconview-item{" is-selected" if sel else ""}">'
            f'<span class="t-image glyph">◈</span><span class="t-text t-label">{name}</span></div>'
            for name, sel in items)
        sel_view = " is-selected" if any(i[1] for i in items) else ""
        hair = '<div class="t-separator"></div>' if cats else ""
        cats += (f'{hair}{head}'
                 f'<div class="t-iconview{sel_view}">{tiles}</div>')
    rows = ""
    for label, desc, control in [
        ("Window borders", "14 px rounded, Aluminium style", "switch-on"),
        ("Translucent panel", "background-blur 14", "switch-on"),
        ("Notifications", "Allow badges and popups", "switch"),
        ("Night light", "Scheduled sunset to sunrise", "select"),
        ("Keyboard layout", "US - English", "static"),
    ]:
        if control.startswith("switch"):
            on = " is-checked" if control == "switch-on" else ""
            ctl = f'<div class="t-switch{on}"><div class="t-slider"></div></div>'
        elif control == "select":
            ctl = ('<div class="t-entry t-select"><span class="t-label">on device</span>'
                   '<span class="glyph">⌄</span></div>')
        else:
            ctl = '<div class="t-label t-dim-label">read-only</div>'
        rows += (
            '\n<div class="t-row">'
            f'<div class="t-box t-row-text"><span class="t-label"><b>{label}</b></span>'
            f'<span class="t-label t-dim-label">{desc}</span></div>{ctl}</div>'
            '\n<div class="t-separator"></div>')
    return f"""
<div class="t-toolbar t-primary-toolbar{backdrop}" id="t-top_bar">
  <div class="t-stack" id="t-header_stack">
    <div class="t-box" id="t-hbox2">
      <div class="t-search-entry" id="t-search_box">
        <div class="t-entry" tabindex="0"><span class="t-image glyph">⌕</span>
          <span class="t-placeholder t-dim-label">Search settings</span>
          <span class="spacer"></span><span class="t-button glyph">✕</span></div>
      </div>
    </div>
    <div class="t-box" id="t-box2">
      <div class="t-button" id="t-button_back"><span class="glyph">←</span></div>
      <div class="t-stackswitcher" id="t-stack_switcher">
        <div class="t-button t-text-button is-checked"><span>Preferences</span></div>
        <div class="t-button t-text-button"><span>Administration</span></div>
        <div class="t-button t-text-button"><span>System</span></div>
      </div>
    </div>
  </div>
</div>
<div class="t-box t-settings-body">
  <div class="t-scrolledwindow t-cs-category-view t-view" id="t-side_view_sw">
    <div class="t-viewport" id="t-viewport2">
      <div class="t-box t-vertical" id="t-category_box">{cats}</div>
    </div>
  </div>
  <div class="t-separator"></div>
  <div class="t-scrolledwindow" id="t-content_box_sw">
    <div class="t-viewport" id="t-content_box">
      <div class="t-box t-vertical" id="t-c_box">
        <div class="t-frame"><div class="t-border">{rows}</div></div>
        <div class="t-frame"><div class="t-border"><div class="t-box t-vertical">
          <div class="t-row"><span class="t-label">Open supported links</span>
            <div class="t-switch is-checked"><div class="t-slider"></div></div></div>
          <div class="t-row"><span class="t-label">Reset to defaults</span>
            <div class="t-button"><span>Reset</span></div></div>
        </div></div></div>
      </div>
    </div>
  </div>
</div>
"""


def files_body() -> str:
    items = "".join(
        f'<div class="t-row t-list-row"><span class="glyph">{"▤▦▣▧▩"[i % 5]}</span>'
        f'<span class="t-label">{n}</span><span class="spacer"></span>'
        f'<span class="t-label t-dim-label">{s}</span></div>'
        for i, (n, s) in enumerate([
            ("Aluminium", "folder"), ("Screenshot 2026-10-29.png", "2.1 MB"),
            ("notes.md", "1 KB"), ("Debian-Iris", "folder"),
            ("iris-theme_0.2.0_all.deb", "1.0 MB"), ("wallpaper.jpg", "880 KB"),
        ]))
    return (
        '<div class="t-toolbar nemo-bar"><div class="t-button">←</div>'
        '<div class="t-button">→</div>'
        '<div class="t-entry path" tabindex="0"><span class="t-label">/home/user/Aluminium</span></div></div>'
        f'<div class="t-list">{items}</div>'
        '<div class="t-menu t-popup-menu-content" id="t-nemo-menu">'
        '<div class="t-popup-menu-item is-selected"><span class="t-label">Open</span></div>'
        '<div class="t-popup-menu-item"><span class="t-label">Open with Files</span></div>'
        '<div class="t-popup-menu-item"><span class="t-label">Copy</span></div>'
        '<div class="t-popup-menu-item"><span class="t-label">Move to Trash</span></div>'
        '<div class="t-separator t-popup-separator-menu-item popup-sep"></div>'
        '<div class="t-popup-menu-item"><span class="t-label">Properties</span></div>'
        '</div>')


def calendar_body() -> str:
    heads = "".join(f'<div class="t-calendar-day-heading">{h}</div>' for h in "MTWTFSS")
    days = "".join(
        f'<div class="t-calendar-day-base {cls}">{d}</div>'
        for d, cls in [(str(i), "t-calendar-other-month-day" if i > 29 else
                        "t-calendar-today" if i == 29 else "t-calendar-work-day")
                       for i in range(1, 35)])
    return (f'<div class="t-popup-menu-content calendar-menu">'
            f'<div class="t-calendar-main-box">'
            f'<div class="t-calendar-month-label"><span>October 2026</span>'
            f'<div><span class="t-button t-flat">‹</span>'
            f'<span class="t-button t-flat">›</span></div></div>'
            f'<div class="t-calendar">{heads}{days}</div></div>'
            f'<div class="t-separator"></div>'
            f'<div class="t-sound-player">'
            f'<div class="t-albumart-widget"><span class="glyph">♫</span></div>'
            f'<div class="player-text"><div class="t-label">Internal Keyboard</div>'
            f'<div class="t-label t-dim-label">Volume 42%</div></div>'
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
  <div class="t-button t-flat notif-close">✕</div>
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
<div class="t-menu t-popup-menu-content popup-menu" id="t-menu">
  <div class="t-entry" id="t-menu-search-entry" tabindex="0">
    <span class="glyph t-menu-search-entry-icon">⌕</span>
    <span class="t-label t-dim-label">Type here to search…</span>
  </div>
  <div class="menu-cols">
    <div class="menu-cats">{cats}</div>
    <div class="menu-apps">{apps}</div>
  </div>
  <div class="t-separator t-popup-separator-menu-item popup-sep"></div>
  <div class="menu-footer">
    <div class="t-button t-flat">⚐ Favorites</div>
    <div class="t-button t-flat">⛭ Settings</div>
    <div class="t-button t-flat">⏻ Power</div>
  </div>
</div>"""


def esc(text: object) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def demo_class(toks: set[str]) -> str:
    return " ".join(sorted(t.lstrip(".#") for t in toks))


# --------------------------------------------------------------------------
# Reachability audit: does every theme rule actually reach an element?
#
# A mock that silently misses half the theme is worse than no mock: everything
# without a rule falls back to scaffolding and *looks like a broken theme*, while
# the mapping tab still claims the CSS is applied. So the preview builds a DOM tree
# from its own markup, matches every generated selector against it including the
# ancestor chain, and auto-creates a demo for anything unreachable. 0 unreachable
# rules is the target, and --print audit fails the build otherwise.
# --------------------------------------------------------------------------
VOID_TAGS = {"img", "br", "hr", "input", "meta", "link"}
SKIP_TAGS = {"script", "style", "head", "html", "body"}
_TAG = re.compile(r"<(/?)([a-zA-Z][\w-]*)([^>]*)>")
_ATTR = re.compile(r"(class|id)=[\x27\x22]([^\x27\x22]*)[\x27\x22]")
# Pseudo-classes a browser resolves at runtime: unjudgeable statically, so the
# element qualifies without them. States the mock can force (a class) must be there.
_RUNTIME_PSEUDO = re.compile(r":(hover|focus|focus-within|active|visited)\b")
# …and the mock classes those pseudos were turned into: for reachability they count
# as satisfied, because the preview sets them on the same events the browser does.
_RUNTIME_CLASSES = (".is-hover", ".is-focused", ".is-active")
_TOKEN = re.compile(r"[.#][-\w]+")


def html_tree(html: str) -> list[dict]:
    """Tag-soup parse good enough for markup this module generated itself."""
    nodes: list[dict] = []
    stack: list[int] = []
    for m in _TAG.finditer(html):
        closing, name, attrs = m.group(1), m.group(2).lower(), m.group(3)
        selfclose = attrs.rstrip().endswith("/")
        if name in SKIP_TAGS:
            continue
        if closing:
            for i in reversed(range(len(stack))):
                if nodes[stack[i]]["tag"] == name:
                    del stack[i:]
                    break
            continue
        toks: set[str] = set()
        for kind, val in _ATTR.findall(attrs):
            for part in val.split():
                toks.add(("." if kind == "class" else "#") + part)
        idx = len(nodes)
        nodes.append({"tag": name, "toks": toks, "parent": stack[-1] if stack else None})
        if not selfclose and name not in VOID_TAGS:
            stack.append(idx)
    return nodes


def sel_compounds(sel: str) -> list[tuple[set[str], bool]]:
    """[(tokens, is-child)] left to right for a descendant / `>` selector."""
    out: list[tuple[set[str], bool]] = []
    text = _RUNTIME_PSEUDO.sub("", sel.strip())
    for cls in _RUNTIME_CLASSES:
        text = text.replace(cls, "")
    for i, segment in enumerate(re.split(r"\s*>\s*", text)):
        for j, comp in enumerate(re.split(r"[ \t]+", segment.strip())):
            if not comp or comp == ">":
                continue
            toks = set(_TOKEN.findall(comp))
            if toks:
                out.append((toks, i > 0 and j == 0))
    return out


def selector_matches(sel: str, nodes: list[dict]) -> bool:
    compounds = sel_compounds(sel)
    if not compounds:
        return True
    last = len(compounds) - 1

    def has(idx: int, toks: set[str]) -> bool:
        return toks <= nodes[idx]["toks"]

    for idx in range(len(nodes)):
        if not has(idx, compounds[last][0]):
            continue
        cur, ok = idx, True
        for toks, child in reversed(compounds[:last]):
            anc = nodes[cur]["parent"]
            if child:
                if anc is None or not has(anc, toks):
                    ok = False
                    break
            else:
                while anc is not None and not has(anc, toks):
                    anc = nodes[anc]["parent"]
                if anc is None:
                    ok = False
                    break
            cur = anc
        if ok:
            return True
    return False


def rule_selectors(css: str) -> list[str]:
    out: list[str] = []
    for block in re.finditer(r"([^{}]+)\{", css):
        head = re.sub(r"/\*.*?\*/", "", block.group(1)).strip()
        if not head or head.startswith(":root"):
            continue
        out.extend(x.strip() for x in head.split(",") if x.strip())
    return out


def dead_selectors(html: str, css: str) -> list[str]:
    nodes = html_tree(html)
    out: list[str] = []
    for sel in rule_selectors(css):
        if sel not in out and not selector_matches(sel, nodes):
            out.append(sel)
    return out


def autofill_html(dead: list[str]) -> tuple[str, int]:
    """One demo per unreachable selector, nested the way the selector is.

    These are placeholders, not claims about widgets — the Components tab marks them
    "auto-demo". Their job is that no theme rule stays orphaned: an orphan reads as
    "the theme does nothing here" and invites a bogus fix to the wrong file.
    """
    groups: dict[str, list[str]] = {}
    for sel in dead:
        compounds = sel_compounds(sel)
        if not compounds:
            continue
        inner = '<span class="t-label">label</span>'
        for toks, _child in reversed(compounds[1:]):
            inner = f'<div class="{demo_class(toks)}">{inner}</div>'
        name = sorted(compounds[-1][0])[0].lstrip(".#")
        groups.setdefault(name, []).append(
            f'<div class="demo"><div class="{demo_class(compounds[0][0])}">{inner}</div>'
            f"<code>{esc(sel)}</code></div>")
    cards = "".join(f'<section class="card"><h3>{name}</h3>{"".join(items)}</section>'
                    for name, items in sorted(groups.items()))
    return cards, sum(len(v) for v in groups.values())


# --------------------------------------------------------------------------
# Hand-built widget samples: real controls, so the theme is judged on widgets
# and not on grey boxes. Anything these cover drops out of the autofill list.
# --------------------------------------------------------------------------
def widget_samples() -> str:
    buttons = "".join(
        f'<div class="t-button {cls}" tabindex="0">{label}</div>'
        for cls, label in [
            ("", "Normal"), ("t-flat", "Flat"), ("t-suggested-action", "Suggested"),
            ("t-destructive-action", "Destructive"), ("t-toggle is-checked", "Toggle on"),
            ("t-toggle", "Toggle off"), ("t-text-button t-image-button", "Icon"),
            ("t-circular", "◉"), ("t-osd", "OSD button"),
        ])
    entries = """
      <div class="t-entry" tabindex="0"><span class="t-label">entry</span></div>
      <div class="t-entry is-focused"><span class="t-label">focused</span></div>
      <div class="t-entry"><span class="t-image">⌕</span><span class="t-label t-dim-label">with icon</span></div>
      <div class="t-entry t-search_entry"><span class="t-label">search</span></div>
      <div class="t-spinbutton"><span>−</span><span class="t-selection">12</span><span>+</span></div>
      <div class="t-textview"><div class="t-text">text view content</div></div>"""
    picks = """
      <div class="t-switch"><div class="t-slider"></div></div>
      <div class="t-switch is-checked"><div class="t-slider"></div></div>
      <div class="t-toggle-switch"><div class="t-toggle-switch-slider"></div></div>
      <div class="t-toggle-switch is-checked"><div class="t-toggle-switch-slider"></div></div>
      <div class="t-checkbutton"><div class="t-check is-checked"></div><span class="t-label">check</span></div>
      <div class="t-checkbutton"><div class="t-check"></div><span class="t-label">unchecked</span></div>
      <div class="t-radiobutton"><div class="t-radio is-checked"></div><span class="t-label">radio</span></div>
      <div class="t-scale"><div class="t-trough"><div class="t-highlight"></div><div class="t-slider"></div></div></div>
      <div class="t-progressbar"><div class="t-progress"><div class="t-trough"></div></div></div>
      <div class="t-levelbar"><div class="t-trough"><div class="t-block t-high"></div><div class="t-block t-high"></div><div class="t-block"></div></div></div>"""
    tabs = """
      <div class="t-notebook">
        <div class="t-header"><div class="t-tabs">
          <div class="t-tab is-checked"><span class="t-label">General</span></div>
          <div class="t-tab"><span class="t-label">Layout</span></div>
          <div class="t-tab"><span class="t-label">Advanced</span></div>
        </div></div>
        <div class="t-stack"><div class="t-row"><span class="t-label">page content</span></div></div>
      </div>"""
    lists = """
      <div class="t-sidebar"><div class="t-list">
        <div class="t-treeview t-view"><div class="t-row is-selected"><span class="t-image">▤</span><span class="t-label">selected row</span></div></div>
        <div class="t-treeview t-view"><div class="t-row"><span class="t-label">plain row</span></div></div>
        <div class="t-treeview t-view is-backdrop"><div class="t-row is-selected"><span class="t-label">backdrop selected</span></div></div>
      </div></div>
      <div class="t-stacksidebar"><div class="t-row t-needs-attention"><span class="t-label">needs attention</span></div></div>
      <div class="t-placessidebar"><div class="t-row"><span class="t-label">places</span></div></div>
      <div class="t-navigation-sidebar"><div class="t-row"><span class="t-label">navigation</span></div></div>"""
    popups = """
      <div class="t-popover"><div class="t-arrow"></div>
        <div class="t-menu"><div class="t-menuitem"><span class="t-label">menu item</span></div></div>
      </div>
      <div class="t-context-menu t-menu"><div class="t-menuitem"><span class="t-label">context menu</span></div></div>
      <div class="t-tooltip"><span class="t-label">A tooltip</span></div>
      <div class="t-infobar t-info"><span class="t-label">info</span></div>
      <div class="t-infobar t-warning"><span class="t-label">warning</span></div>
      <div class="t-infobar t-error"><span class="t-label">error</span></div>
      <div class="t-statusbar"><span class="t-label">status</span></div>
      <div class="t-scrollbar"><div class="t-overlay-indicator"></div></div>"""
    dialogs = """
      <div class="t-dialog t-popup-dialog t-modal-dialog">
        <div class="t-dialog-content">
          <div class="t-run-dialog"><span class="t-label">Press a key combination</span>
            <div class="t-entry t-run-dialog-entry"><span class="t-label">Super+I</span></div></div>
          <div class="t-prompt-dialog"><span class="t-label">Password</span>
            <div class="t-entry t-prompt-dialog-password-entry"><span class="t-label">••••</span></div></div>
          <div class="t-polkit-dialog"><span class="t-label">Authentication required</span></div>
          <div class="t-end-session-dialog"><span class="t-label">Log out?</span></div>
        </div>
        <div class="t-dialog-button-box">
          <div class="t-button t-dialog-button">Cancel</div>
          <div class="t-button t-dialog-button t-suggested-action">OK</div>
        </div>
      </div>"""
    nemo = """
      <div class="t-window t-nemo-window">
        <div class="t-nemo-window-toolbar t-toolbar"><div class="t-button">←</div>
          <div class="t-entry t-pathentrybar"><span class="t-label">/home</span></div></div>
        <div class="t-nemo-window-pane"><div class="t-widget t-entry">
          <span class="t-label">type to search</span></div></div>
      </div>
      <div class="desktop-well"><div class="t-nemo-desktop t-nemo-desktop-icon-view"><div class="t-clutter-icon-container">
        <div class="t-icon"><span class="glyph">▤</span><span class="t-label t-nemo-desktop t-nemo-canvas-item">Trash</span></div>
        <div class="t-icon"><span class="glyph">▦</span><span class="t-label t-nemo-desktop t-nemo-canvas-item is-selected">Home</span></div></div></div></div>"""
    groups = [
        ("buttons", buttons), ("entries & numbers", entries), ("switches, checks, bars", picks),
        ("tabs / notebook", tabs), ("sidebars & lists", lists), ("popovers, menus, hints", popups),
        ("dialogs", dialogs), ("nemo", nemo),
    ]
    return "".join(f'<section class="card"><h3>{name}</h3><div class="row">{html}</div></section>'
                   for name, html in groups)


# --------------------------------------------------------------------------
# Shell component samples (Cinnamon's own surfaces, named as Cinnamon names them)
# --------------------------------------------------------------------------
SHELL_STATES = r"""
  <div class="card"><div class="card-title">Panel states (the mock shows the states the desktop only flashes)</div>
    <div class="t-panel is-highlight panelrow">
      <div id="t-panelLeft" class="t-panelLeft is-dnd"><div class="t-applet-box"><span class="t-applet-label">Activities</span></div></div>
      <div id="t-panelCenter" class="t-panelCenter is-dnd"><div class="t-window-list"><div class="t-window-list-item-box is-focused"><span>🗔</span><span class="t-window-list-item-label">firefox</span></div></div></div>
      <div id="t-panelRight" class="t-panelRight is-dnd"><div class="t-applet-box is-hover"><span class="glyph">🔊</span></div></div>
    </div>
    <div class="t-panel-corner">panel-corner</div>
    <div class="t-applet-separator"><div class="t-applet-separator-line"></div></div>
    <div class="t-spacer-box">spacer</div>
    <div class="t-panel-launchers"><div class="t-launcher">launcher</div></div>
    <div class="t-window-list-item-box is-urgent">urgent window</div>
    <div class="t-systray">
      <div class="t-system-status-icon-menu-item">network</div>
      <div class="t-status-icon-button-inactive">inactive</div>
      <div class="t-status-icon-button-active">active</div>
    </div>
  </div>
  <div class="card"><div class="card-title">Tooltip, corner bar, snap helper</div>
    <div id="t-Tooltip" class="t-tooltip">Grow a tomato in spring</div>
    <div class="t-applet-cornerbar-box"><div class="t-applet-cornerbar">⋮</div></div>
    <div class="t-context-menu"><span class="t-window-image">🗔</span>
      <span class="t-window-caption">Alt + F4</span></div>
    <div class="t-hover-click-box"><div class="t-contents">click for <b>3 windows</b></div></div>
    <div class="t-tile-preview">tile preview</div>
    <div class="t-tile-hud">snap helper</div>
    <div class="t-popup-menu-search-entry"><span class="glyph">⌕</span> search menu</div>
    <div class="t-icon-button"><span>⋯</span></div>
  </div>
  <div class="card"><div class="card-title">Unfocused (backdrop) window</div>
    <div class="t-window t-solid-csd is-backdrop">
      <div class="t-headerbar t-titlebar is-backdrop">
        <div class="t-button t-flat is-checked"><span>on</span></div>
        <label class="t-title">Iris</label><label class="t-subtitle">unfocused</label>
        <div class="t-window-controls"><div class="t-button"><span>—</span></div></div>
      </div>
      <div class="t-box t-statusbar"><span class="t-label t-dim-label">3 items</span></div>
    </div>
    <p class="hint">A browser cannot lose focus the way a window manager does, so the
    mock models <code>:backdrop</code> with the dim knob; the desktop tab under
    <code>?dim=1</code> carries <code>#top_bar</code> in that state too.</p>
  </div>
"""


def shell_samples() -> str:  # noqa: C901 - data, not logic
    window_list = "".join(
        f'<div class="t-window-list-item-box t-{pos} {state}">'
        f'<span class="t-applet-icon">▤</span><span class="t-window-list-item-label">Firefox</span></div>'
        for pos, state in [("top", ""), ("bottom", "is-checked"), ("left", ""), ("right", "")])
    grouped = """
      <div class="t-grouped-window-list-item-list">
        <div class="t-grouped-window-list-item-box is-checked">
          <span class="t-grouped-window-list-item-label">Files</span>
          <div class="t-grouped-window-list-badge"><span class="t-grouped-window-list-number-label">3</span></div>
        </div>
        <div class="t-grouped-window-list-item-box t-demands-attention">
          <span class="t-grouped-window-list-button-label">Terminal</span>
        </div>
      </div>
      <div class="t-popup-menu-content t-grouped-window-list-thumbnail-menu">
        <div class="t-thumbnail-box"><div class="t-thumbnail"><span class="t-label">window</span></div>
          <span class="t-window-caption">window caption</span></div>
      </div>"""
    menu = """
      <div class="t-popup-menu t-popup-menu-content">
        <div class="t-popup-menu-item-container"><div class="t-popup-menu-item is-selected">
          <span class="t-popup-menu-icon">▤</span><span class="t-label">Places</span>
          <span class="t-popup-menu-arrow">›</span></div></div>
        <div class="t-popup-menu-item t-popup-inactive-menu-item"><span class="t-label">Recent</span></div>
        <div class="t-separator t-popup-separator-menu-item"></div>
        <div class="t-popup-menu-item t-popup-sub-menu"><span class="t-label">Submenu</span></div>
        <div class="t-popup-menu-item t-popup-combo-menu"><span class="t-label">Combo</span></div>
        <div class="t-popup-slider-menu-item"><div class="t-slider"><div class="t-handle"></div></div>
          <span class="t-label">volume</span></div>
        <div class="t-icon-button"><span class="glyph">⚙</span></div>
        <div class="t-check-box"><span class="t-label">checkbox</span></div>
      </div>"""
    appmenu = """
      <div class="t-popup-menu t-appmenu">
        <div class="t-entry" id="t-appmenu-search-entry"><span class="t-menu-search-entry-icon">⌕</span>
          <span class="t-label t-dim-label">Type to search</span></div>
        <div class="t-appmenu-categories">
          <div class="t-appmenu-category-button is-selected"><span class="t-appmenu-category-button-label">Favorites</span></div>
          <div class="t-appmenu-category-button"><span class="t-appmenu-category-button-label">Accessories</span></div>
        </div>
        <div class="t-appmenu-apps">
          <div class="t-appmenu-application-button is-selected"><span class="t-appmenu-application-button-label">Files</span></div>
          <div class="t-appmenu-application-button"><span class="t-appmenu-application-button-label">Terminal</span></div>
        </div>
        <div class="t-appmenu-system-buttons">
          <div class="t-button t-appmenu-system-button">⏻</div>
          <div class="t-button t-appmenu-system-button">⎋</div>
        </div>
      </div>"""
    media = """
      <div class="t-albumart-widget">
        <div class="t-albumart-album"><span class="glyph">♫</span></div>
        <div class="t-albumart-track-info-box">
          <span class="t-albumart-title">Track name</span>
          <span class="t-albumart-artist">Artist</span></div>
        <div class="t-albumart-controls"><div class="t-button t-flat">⏮</div>
          <div class="t-button t-flat">⏭</div></div>
      </div>
      <div class="t-sound-player"><div class="t-progress"><div class="t-trough"></div></div></div>"""
    extras = """
      <div class="t-user-widget"><div class="t-user-icon"><span class="glyph">☻</span></div>
        <span class="t-user-widget-label">user</span></div>
      <div class="t-notification-applet-padding"><div class="t-notification">
        <div class="t-notification-icon"><span class="glyph">◍</span></div>
        <div class="t-notification-body">
          <span class="t-notification-title">Title</span>
          <span class="t-notification-label">Body text</span></span>
          <div class="t-notification-button">Action</div>
          <div class="t-notification-icon-button">✕</div>
        </div></div></div>
      <div class="t-info-osd"><span class="t-icon">♊</span><span class="t-label">Volume</span></div>
      <div class="t-media-keys-osd"><span class="t-icon">♫</span></div>
      <div class="t-workspace-switch-osd"><div class="t-workspace-switch-osd-indicator-box">
        <span class="t-workspace-switch-osd-indicator"></span></div></div>
      <div class="t-applet-cornerbar-box"><div class="t-applet-cornerbar">cornerbar</div></div>
      <div class="t-hover-click-box"><div class="t-hover-click-button"><span class="glyph">＋</span></div></div>
      <div class="t-tile-preview"><div class="t-tile-hud">tile</div></div>
      <div class="t-osd-window"><div class="t-osd">osd window</div></div>"""
    alttab = """
      <div class="t-altTabPopup" id="t-altTabPopup">
        <div class="t-switcher-list"><div class="t-switcher-list-item-container">
          <div class="t-item-box is-selected"><span class="t-icon">▤</span><span class="t-label">Settings</span></div>
          <div class="t-item-box"><span class="t-icon">◍</span><span class="t-label">Firefox</span></div>
        </div></div>
        <div class="t-switcher-list"><div class="t-switcher-preview-backdrop">preview</div></div>
        <div class="t-icon-button t-switcher-arrow">‹</div>
        <div class="t-icon-button t-switcher-arrow">›</div>
      </div>"""
    expo = """
      <div id="t-overview" class="t-overview">
        <div id="t-expo" class="t-expo"><div class="t-workspace-graph">
          <div class="t-workspace is-selected"><div class="t-expo-workspace-thumbnail-frame">
            <div class="t-window"><div class="t-window-caption">window</div></div></div>
            <div class="t-entry t-expo-workspaces-name-entry"><span class="t-label">Workspace 1</span></div></div>
          <div class="t-workspace"><span class="t-label">2</span></div>
        </div></div>
        <div class="t-lightbox"></div>
      </div>"""
    calendar = """
      <div class="t-popup-menu-content t-calendar-events-main-box">
        <div class="t-calendar">
          <div class="t-calendar-main-box">
            <div class="t-calendar-month-label"><span class="t-label">October 2026</span>
              <div><div class="t-button t-flat t-calendar-change-month-back">‹</div>
                   <div class="t-button t-flat t-calendar-change-month-forward">›</div></div></div>
            <div class="t-calendar-day-heading">Mo</div>
            <div class="t-calendar-day-base t-calendar-work-day">1</div>
            <div class="t-calendar-day-base t-calendar-today">2</div>
            <div class="t-calendar-day-base t-calendar-not-today is-selected">3</div>
            <div class="t-calendar-day-base t-calendar-nonwork-day">4</div>
            <div class="t-calendar-day-base t-calendar-other-month-day">5</div>
          </div>
          <div class="t-separator"></div>
          <div class="t-calendar-events-view"><div class="t-calendar-events-main-box">
            <div class="t-calendar-events-date-label">Today</div>
            <div class="t-calendar-events-event"><span class="t-label">10:00 Standup</span></div>
          </div></div>
        </div>
      </div>"""
    states = SHELL_STATES
    groups = [
        ("window list & grouped window list", window_list + grouped),
        ("menus (popup)", menu), ("the app menu", appmenu),
        ("media player", media), ("widgets around the panel", extras),
        ("alt-tab", alttab), ("expo / overview", expo), ("calendar", calendar),
        ("states the desktop only flashes", states),
    ]
    return "".join(f'<section class="card"><h3>{name}</h3><div class="row">{html}</div></section>'
                   for name, html in groups)


def gallery(cards: str) -> str:
    return f'<div class="gallery">{cards}</div>'


def components_html(gen: Gen) -> str:
    cards, n = gen.autofill
    return f"""
<section class="doc">
  <h2>Components</h2>
  <p class="lead">Styled by the theme file only. The two groups below are hand-built
  from the names the real widgets use; the last group exists because the mock had no
  element for those rules — instead of leaving them orphaned (which reads as "the
  theme does nothing"), each gets a demo box carrying the same classes, so you can see
  exactly what the theme assigns and judge whether that is what you want.</p>
  {gallery(shell_samples() + widget_samples())}
  <h2>Auto-demo — {n} rule(s) the mock did not otherwise reach</h2>
  {gallery(cards) if cards else '<p class="lead">none: every theme rule reaches a hand-built mock element.</p>'}
</section>"""


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
    n_un = sum(len(v) for v in gen.untranslated.values())
    return f"""
<section class="doc">
  <h2>Mapping — theme rule → mock element</h2>
  <p class="lead">{len(gen.report)} rules drive the mock, in file order.
  Rules reaching no mock element: <b>{len(gen.dead)}</b> (0 means every rule you wrote
  is visible somewhere in this preview; <code>make preview</code> fails the build otherwise).
  Anything the mock cannot style at all is listed, never dropped quietly.</p>
  <table class="map"><thead><tr><th>rule</th><th>selector in theme file</th>
  <th>mock node</th><th>declarations</th></tr></thead><tbody>{rows}</tbody></table>

  <h2>Approximated on purpose</h2><ul>{approx}</ul>
  <h2>Mock deviations (read before judging)</h2><ul class="deviations">{deviations}</ul>
  <h2>Not translated ({n_un})</h2>
  <ul>{untr or '<li>none</li>'}</ul>
  <h2>No web/mock target ({sum(len(v) for v in gen.skipped.values())})</h2>
  <ul>{skip or '<li>none</li>'}</ul>
  <h2>Colour tokens from <code>@define-color</code></h2>
  <div class="swatches">{swatches}</div>
</section>"""


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
    return "&".join(f"{k}={v:g}" if isinstance(v, float) else f"{k}={v}"
                    for k, v in merged.items())


def controls_html(gen: Gen) -> str:
    o = gen.opts

    def rng(name, label, lo, hi, step, cur, unit=""):
        val = "" if cur is None else f"{cur:g}"
        shown = "theme default" if cur is None else f"{cur:g}{unit}"
        return (f'<label>{label}<input type="range" data-knob="{name}" min="{lo}" '
                f'max="{hi}" step="{step}" value="{val}">'
                f"<output>{shown}</output></label>")

    sel = "".join(
        f'<option value="{v}"{" selected" if v == o.get("panel", "bottom") else ""}>{t}</option>'
        for v, t in [("bottom", "bottom (taskbar)"), ("top", "top"),
                     ("left", "left / vertical"), ("right", "right / vertical")])
    tab = o.get("tab", "desk")
    checks = "".join(
        f'<label><input type="checkbox" data-flag="{k}"{" checked" if o.get(k) else ""}> '
        f"{t}</label>"
        for k, t in [("dim", "unfocused windows"), ("hl", "panel highlight"),
                     ("dnd", "panel drag zones"), ("grid", "alignment grid"),
                     ("labels", "node labels"),
                     ("calm", "hide overlays over windows"),
                     ("full", "full sampler scene")])
    return f"""
<aside class="controls">
  <div class="ctl-head"><b>Iris preview</b><small>rendered from the repo files</small>
    <small>rules not reaching the mock: <b>{len(gen.dead)}</b></small></div>
  <label>panel position<select data-knob="panel">{sel}</select></label>
  {rng("blur", "background-blur", 0, 30, 1, o.get("blur"), "px")}
  {rng("alpha", "surface alpha", 20, 100, 1, o.get("alpha"), "%")}
  {rng("radius", "radius scale", 0, 200, 5, o.get("radius"), "%")}
  <div class="toggles">{checks}</div>
  <nav class="tabs">
    <a class="{'on' if tab == 'desk' else ''}" href="?{q(o, tab='desk')}">desktop</a>
    <a class="{'on' if tab == 'comp' else ''}" href="?{q(o, tab='comp')}">components</a>
    <a class="{'on' if tab == 'map' else ''}" href="?{q(o, tab='map')}">mapping</a>
    <a class="{'on' if tab == 'src' else ''}" href="?{q(o, tab='src')}">source</a>
  </nav>
  <p class="warn"><b>Web mock, not a GTK/St render.</b> Font hinting, Clutter's blur
  cost and Muffin's frame clipping differ; the components tab is the reliable way to
  judge what the theme assigns. <a href="/api/check" target="_blank">run
  tools/check-theme.py</a></p>
</aside>"""


def scene_html(gen: Gen) -> str:
    o = gen.opts
    body_cls = " ".join(c for c in ("dim", "grid", "labels") if o.get(c))
    if not o.get("full"):
        # the product shot: wallpaper + drawer + both panels, nothing else. The
        # full sampler scene (windows, calendar, overlays) lives under ?full=1.
        return f"""
<div class="desk {body_cls}">
  <div class="wallpaper"><img src="/assets/wallpaper.png" alt=""></div>
  {menu_html()}
  {panel_html(gen)}
</div>"""
    gear, page_glyph = "\u2699", "\u25a4"
    files = window_html("Aluminium", files_body(), "win-files", bool(o.get("dim")), "",
                        "Internal SSD", "default-decoration")
    settings = window_html("Personalizations", settings_body(gen), "win-settings",
                           False, gear, "Cinnamon Settings")
    # the transient overlays sit on top of the windows, which is what a real session
    # does but not what you want while judging layout: ?calm=1 keeps just the
    # centered drawer + calendar. (This whole scene is ?full=1; the default desk
    # is the clean product shot above.)
    popovers = ("" if o.get("calm") else
                f"{notification_html()}{osd_html()}")
    editor = window_html(
        "DESIGN.md",
        "<div class='t-textview'><div class='t-row'><span class='t-label'>"
        "## Tokens</span></div><div class='t-row'>"
        "<span class='t-label t-dim-label'>accent #4c7fd0 \u00b7 radius 14px</span>"
        "</div></div>",
        "win-editor", bool(o.get("dim")), page_glyph, "Text Editor", "tiled")
    return f"""
<div class="desk {body_cls}">
  <div class="wallpaper"><img src="/assets/wallpaper.png" alt=""></div>
  {files}
  {settings}
  {editor}
  {menu_html()}
  <div class="cal-anchor">{calendar_body()}</div>
  {popovers}
  {panel_html(gen)}
</div>"""


def page(gen: Gen) -> str:
    tab = gen.opts.get("tab", "desk")
    if tab == "comp":
        main = components_html(gen)
    elif tab == "map":
        main = mapping_html(gen)
    elif tab == "src":
        main = source_html(gen)
    else:
        main = scene_html(gen)
    body_cls = " ".join(c for c in ("dim", "grid", "labels") if gen.opts.get(c))
    return (f"<!doctype html><html lang=id><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>Iris preview</title>"
            f"<link rel=stylesheet href='/preview-base.css'>"
            f"<link rel=stylesheet href='/preview.css'>"
            f"</head><body class='theme-root {body_cls}' data-tab='{tab}'>"
            f"{main}{controls_html(gen)}<script src='/preview.js'></script></body></html>")


# --------------------------------------------------------------------------
# Build pipeline: css -> scene -> audit -> autofill -> page. The audit has to run
# against the finished markup, so page() cannot be built in one pass.
# --------------------------------------------------------------------------
def mock_dom(gen: Gen) -> str:  # noqa: ARG001 - kept for call-site symmetry
    """All markup the mock can ever show, across tabs and across preview states.

    The audit runs against this instead of a single tab: a rule whose element lives
    in the Components tab, or in a state the user switches on with ?dim=1, is not
    unreachable. :backdrop is exactly such a state - a browser cannot lose focus the
    way a window manager does - so the mock models it with the dim knob and the
    audit checks the knob being on.
    """
    # Fixed set of states, deliberately not the request's knobs: the audit answers
    # "can this rule land somewhere in the mock?", which must not change because
    # somebody loaded ?calm=1 — or because the desk tab defaults to the clean
    # product shot while the sampler scene lives under ?full=1.
    variants = [{"full": 1}, {"dim": 1, "full": 1}, {"hl": 1, "dnd": 1, "full": 1}]
    dom = "".join(scene_html(Gen(v)) for v in variants)
    return dom + shell_samples() + widget_samples()


def build(opts: dict) -> tuple[Gen, str]:
    gen = Gen(opts)
    css = gen.css()
    # two passes: whatever the hand-built widgets do not reach becomes a demo box,
    # and the audit is then re-run including those boxes so the reported count is
    # the truth about the final page.
    gen.dead = dead_selectors(mock_dom(gen), css)
    gen.autofill = autofill_html(gen.dead)
    gen.dead = dead_selectors(mock_dom(gen) + gen.autofill[0], css)
    return gen, page(gen)


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
// "node labels": annotate each mock element with the theme node it stands for,
// derived from its own t-* classes so it can never drift from the markup.
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
                + '.t-applet-box, .t-popup-menu-item, .t-calendar-day-base, '
                + '.t-demo-item, .t-workspace, .t-item-box, .t-tab, .t-appmenu-application-button, '
                + '.t-appmenu-category-button';
document.addEventListener('click', ev => {
  const el = ev.target.closest(CLICKABLE);
  if (!el || el.closest('.controls')) return;
  if (el.matches('.t-switch, .t-toggle-switch')) { el.classList.toggle('is-checked'); return; }
  const exclusive = 'is-selected';
  if (el.classList.contains(exclusive)) { el.classList.remove(exclusive); return; }
  const box = el.parentElement;
  if (box) [...box.children].forEach(s => s.classList.remove(exclusive));
  el.classList.add(exclusive);
});
// :focus and :active as the theme uses them: a mock element is not a GtkButton, so
// the preview copies the real events onto the classes the CSS asks for.
document.addEventListener('focusin', ev => ev.target.classList.add('is-focused'));
document.addEventListener('focusout', ev => ev.target.classList.remove('is-focused'));
const PRESSABLE = '.t-button, .t-applet-box, .t-popup-menu-item, .t-switch, '
                + '.t-iconview-item, .t-tab, .t-titlebutton, .t-menuitem';
document.addEventListener('pointerdown', ev => {
  const el = ev.target.closest(PRESSABLE);
  if (el && !el.closest('.controls')) el.classList.add('is-active');
}, true);
const release = () => document.querySelectorAll('.is-active')
  .forEach(el => el.classList.remove('is-active'));
document.addEventListener('pointerup', release);
document.addEventListener('pointercancel', release);
document.querySelectorAll('[data-flag]').forEach(el => {
  el.addEventListener('change', () => {
    el.checked ? q.set(el.dataset.flag, '1') : q.delete(el.dataset.flag);
    go();
  });
});
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "IrisPreview/1.0"

    def _send(self, code: int, ctype: str, data: bytes | str) -> None:
        # encoding here rather than at every call site: a str reaching wfile.write
        # raises TypeError after the headers are already flushed, which a browser
        # reports as a truncated download instead of an error - hard to read as
        # "your preview server has a bug".
        if isinstance(data, str):
            data = data.encode()
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
                _gen, html = build(opts)
            except Exception as exc:  # noqa: BLE001 - show it, do not drop the socket
                html = (f"<pre>preview generator bug, not a theme bug:\n\n{exc!r}\n\n"
                        "fix tools/preview.py and reload.</pre>")
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
                self._send(404, "text/plain", b"wallpapers/iris-aluminium-dark.png not found")
        elif path == "/api/report":
            gen, _html = build(opts)
            payload = {"rules": gen.report, "unreachable": gen.dead,
                       "untranslated": gen.untranslated, "skipped": gen.skipped}
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(payload, indent=1).encode())
        elif path == "/api/check":
            proc = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check-theme.py")],
                                  capture_output=True, text=True, cwd=ROOT)
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-60:]
            text = f"tools/check-theme.py -> exit={proc.returncode}\n\n" + "\n".join(tail)
            self._send(200, "text/plain; charset=utf-8", text.encode())
        elif path == "/api/audit":
            gen, _html = build(opts)
            text = "\n".join(gen.dead) or "every theme rule reaches a mock element"
            self._send(200, "text/plain; charset=utf-8",
                       f"{len(gen.dead)} unreachable after auto-demo\n{text}\n".encode())
        else:
            self._send(404, "text/plain; charset=utf-8",
                       b"endpoints: /  /preview.css  /preview-base.css  /preview.js\n"
                       b"           /assets/wallpaper.png  /api/report  /api/audit  /api/check\n")

    def log_message(self, fmt: str, *args) -> None:
        if "--verbose" in sys.argv:
            super().log_message(fmt, *args)


def main() -> int:
    ap = argparse.ArgumentParser(description="web preview of the Iris theme")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--print", choices=["css", "html", "report", "audit"],
                    help="render once to stdout and exit (no server)")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--max-demo", type=int, default=60,
                    help="--print audit: also fail when more than this many rules only "
                         "reach an auto-demo box instead of a hand-built widget")
    args = ap.parse_args()

    if args.print == "audit":
        gen, _html = build({})
        still = gen.dead
        for sel in still:
            print(f"UNREACHABLE  {sel}")
        n = gen.autofill[1]
        print(f"{len(gen.report)} rule(s) mapped, {n} carried only by an auto-demo, "
              f"{len(still)} unreachable")
        if still:
            print("every theme rule must land on a mock element: add the node to the "
                  "scene or to a Components sample (tools/preview.py)", file=sys.stderr)
            return 1
        if n > args.max_demo:
            print(f"auto-demos grew past --max-demo {args.max_demo}: the theme styles "
                  f"widgets the mock no longer builds, so the desktop itself is what "
                  f"loses styling - rebuild the missing element, do not raise the cap",
                  file=sys.stderr)
            return 1
        return 0

    if args.print:
        gen = Gen({})
        if args.print == "css":
            print(gen.css())
        elif args.print == "report":
            _g, _h = build({})
            print(json.dumps({"rules": _g.report, "unreachable": _g.dead,
                              "untranslated": _g.untranslated, "skipped": _g.skipped},
                             indent=1))
        else:
            _g, html = build({})
            print(html)
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
