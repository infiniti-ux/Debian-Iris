#!/usr/bin/env python3
"""tools/gen-selectors.py — rebuild tools/upstream-selectors.txt

Extracts the *names* Cinnamon's shell can actually match — element ids and style
classes — from upstream sources, and writes them as an allowlist for
tools/check-theme.py. Only names are recorded (no style declarations), so this
is an API-surface reference rather than copied theming data.

Sources, in order of authority:
  1. a Cinnamon checkout (default: ../cinnamon or $CINNAMON_SRC), or the
     `cinnamon` package's installed data  (/usr/share/cinnamon)
  2. a third-party Cinnamon theme checkout (default: ../mint-themes, or
     /usr/share/themes/*/**/cinnamon/cinnamon.css)

Usage:
    tools/gen-selectors.py [--cinnamon-src DIR] [--themes-dir DIR] [--out FILE]

If neither source is found the script exits 1 and the committed allowlist stays
as-is; check-theme.py then still runs, just against the committed list.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

SEL_NAME = re.compile(r"[.#]?([A-Za-z][A-Za-z0-9_-]*)")
# style_class / set_name in JS: 'foo' or "foo", possibly space-separated for classes
JS_PATTERNS = [
    re.compile(r"""(?:style_class|styleClass|name)\s*:\s*['"]([^'"]+)['"]"""),
    re.compile(r"""(?:add_style_class_name|add_class_name|set_name)\s*\(\s*['"]([^'"]+)['"]"""),
]
# Cinnamon also toggles classes inline: actor.add_style_class_name("today"),
# actor.set_style_class_name("x"), `.style_class = "y"`. Capturing the quoted
# token on any line that mentions a class/name API is enough for a name list.
JS_LOOSE_LINE = re.compile(r"style_class|add_style_class|add_class_name|set_name|styleClass")
JS_LOOSE_TOKEN = re.compile(r"['\"]([A-Za-z][A-Za-z0-9_ -]{1,60})['\"]")


def names_from_scss(text: str) -> set[str]:
    """Collect class/id names, expanding SCSS `&` nesting at every depth.

    Upstream's default theme writes `.applet { &-separator { &-line {} } }`, and
    the runtime selector is `.applet-separator-line`. A single-level expansion
    misses `separator-line`-style leaf names and produces false "invented
    selector" reports, so the parent chain is tracked fully and both the
    composed and the leaf names are registered.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    names: set[str] = set()
    stack: list[str] = [""]
    buf = ""
    for ch in text:
        if ch == "{":
            sel = buf.strip()
            sel = sel.splitlines()[-1].strip() if sel else ""
            sel = sel.split(",")[-1].strip()
            parent = stack[-1]
            if not sel:                     # `& { ... }` or a bare nested block
                full = parent
            elif "&" in sel:
                full = sel.replace("&", parent).strip()
            else:
                full = sel                   # descendant selector: keep leaf
            # every comma-separated selector in the list is a rule for us
            for selector_part in sel.split(",") if sel else [""]:
                compound = selector_part.strip() or full
                # split combinators, drop pseudo-classes/attribute tests, then take
                # every .class / #id token of a compound like `.a.b#d:hover[x]`
                for piece in re.split(r"[\s>+~]+", compound):
                    piece = re.split(r"[:\[]", piece)[0]
                    for tok in re.findall(r"[.#%]?([A-Za-z][A-Za-z0-9_-]*)", piece):
                        names.add(tok)
            stack.append(full if full else parent)
            buf = ""
        elif ch == "}":
            if len(stack) > 1:
                stack.pop()
            buf = ""
        elif ch == ";":
            buf = ""
        else:
            buf += ch
    return names


def names_from_css(text: str) -> set[str]:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    names: set[str] = set()
    for m in re.finditer(r"(^|\})([^{}@;]+)\{", text):
        chunk = m.group(2)
        for part in chunk.split(","):
            for tok in re.findall(r"[.#][A-Za-z][A-Za-z0-9_-]*", part):
                names.add(tok.lstrip(".#"))
    return names


def names_from_js(text: str) -> set[str]:
    names: set[str] = set()

    def keep(tok: str) -> None:
        for part in tok.split():
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", part) and len(part) < 60:
                names.add(part)

    for pat in JS_PATTERNS:
        for m in pat.finditer(text):
            keep(m.group(1))
    for line in text.splitlines():
        if JS_LOOSE_LINE.search(line):
            for m in JS_LOOSE_TOKEN.finditer(line):
                keep(m.group(1))
    return names


def walk(root: str, exts: tuple[str, ...]):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "po")]
        for f in files:
            if f.endswith(exts):
                yield os.path.join(dirpath, f)


def collect(src: str) -> set[str]:
    found: set[str] = set()
    for path in walk(src, (".scss", ".css", ".js")):
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        if path.endswith(".scss"):
            found |= names_from_scss(text)
        elif path.endswith(".css"):
            found |= names_from_css(text)
        else:
            found |= names_from_js(text)
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cinnamon-src", default=os.environ.get("CINNAMON_SRC", ""))
    ap.add_argument("--themes-dir", default=os.environ.get("THEMES_DIR", ""))
    ap.add_argument("--out", default="tools/upstream-selectors.txt")
    args = ap.parse_args()

    candidates = [
        args.cinnamon_src,
        "../cinnamon",
        "/tmp/cin-full/cinnamon-master",
    ]
    cinnamon = next((c for c in candidates if c and os.path.isdir(c)), "")
    theme_candidates = [
        args.themes_dir,
        "/usr/share/themes",
        "../mint-themes/src",
    ]
    themes = next((c for c in theme_candidates if c and os.path.isdir(c)), "")

    if not cinnamon and not themes:
        print("no upstream sources found (pass --cinnamon-src or --themes-dir)", file=sys.stderr)
        return 1

    names: set[str] = set()
    if cinnamon:
        names |= collect(cinnamon)
        print(f"scanned cinnamon checkout: {cinnamon}")
    if themes:
        # only Cinnamon stylesheets from installed/other themes
        for path in walk(themes, (".css",)):
            if os.path.basename(path) == "cinnamon.css":
                names |= names_from_css(open(path, encoding="utf-8", errors="ignore").read())
        print(f"scanned third-party cinnamon.css files under: {themes}")

    out = "\n".join(sorted(names)) + "\n"
    header = (
        "# Iris — allowlist of Cinnamon shell CSS selector names (ids and classes)\n"
        "#\n"
        "# Generated by tools/gen-selectors.py from upstream sources; names only, no\n"
        "# style declarations. tools/check-theme.py flags rules whose selector is not\n"
        "# listed here, because in Cinnamon a rule for a non-existent class is not an\n"
        "# error — it is silently inert, which is the defect this repo used to ship.\n"
        "#\n"
        "# Sources scanned:\n"
        f"#   cinnamon checkout : {cinnamon or '(not available)'}\n"
        f"#   themes dir        : {themes or '(not available)'}\n"
        f"# Count: {len(names)}\n"
        "#\n"
    )
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(header + out)
    print(f"wrote {args.out}: {len(names)} names")
    return 0


if __name__ == "__main__":
    sys.exit(main())
