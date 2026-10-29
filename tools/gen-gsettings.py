#!/usr/bin/env python3
"""tools/gen-gsettings.py — rebuild tools/upstream-gsettings.txt

The profile in config/gsettings/iris.gsettings is the only place this skin talks to
the desktop, and every key in it has to be real: a key that no schema defines is
accepted silently by dconf, stored, and never read by anything — inert config that
looks like config. This tool snapshots the (schema, key) pairs Cinnamon actually
defines so tools/check-theme.py can reject invented ones.

Sources, in order of authority:
  1. the compiled schemas on this machine — /usr/share/glib-2.0/schemas/*.gschema.xml
     (a Cinnamon install has them; no network, no checkout needed)
  2. upstream checkouts, if given: $CINNAMON_SRC / $CINNAMON_DESKTOP_SRC / $NEMO_SRC
     (their .gschema.xml[.in] files are parsed the same way)

Usage:
    tools/gen-gsettings.py [--schemas-dir DIR] [--cinnamon-src DIR]
                           [--cinnamon-desktop-src DIR] [--nemo-src DIR] [--out FILE]

Exits 1 when no source produced a single schema, so a failed regeneration cannot
quietly shrink the allowlist; check-theme.py keeps using the committed list.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

SCHEMA_ID_RE = re.compile(r"<schema\s+id=\"([\w.-]+)\"")


def schemas_from_xml(path: str) -> dict[str, set[str]]:
    """{schema id: {key names}} for one gschema file; nested ids are kept too."""
    text = open(path, encoding="utf-8", errors="replace").read()
    # .gschema.xml.in files carry @GETTEXT_PACKAGE@ placeholders; they never appear
    # in an id or key name, so parsing the file as-is is safe.
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        # a stray entity in an upstream description: fall back to regex so the id/key
        # surface is still captured instead of silently dropping the whole file
        out: dict[str, set[str]] = {}
        for m in SCHEMA_ID_RE.finditer(text):
            block = text[m.end():]
            nxt = block.find("<schema ")
            out.setdefault(m.group(1), set()).update(
                k.group(1) for k in re.finditer(r"<key\s+[^>]*name=\"([-\w]+)\"",
                                                block if nxt < 0 else block[:nxt]))
        return out
    found: dict[str, set[str]] = {}

    def walk(node) -> None:
        for child in node:
            if child.tag == "schema":
                sid = child.get("id")
                if sid:
                    found.setdefault(sid, set()).update(
                        k.get("name") for k in child.findall("key") if k.get("name"))
            walk(child)

    walk(root)
    return {k: v for k, v in found.items() if v}


def merge(dst: dict[str, set[str]], src: dict[str, set[str]]) -> int:
    added = 0
    for sid, keys in src.items():
        before = len(dst.get(sid, ()))
        dst.setdefault(sid, set()).update(keys)
        added += len(dst[sid]) - before
    return added


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--schemas-dir", default="/usr/share/glib-2.0/schemas")
    ap.add_argument("--cinnamon-src", default=os.environ.get("CINNAMON_SRC", "../cinnamon"))
    ap.add_argument("--cinnamon-desktop-src",
                    default=os.environ.get("CINNAMON_DESKTOP_SRC", "../cinnamon-desktop"))
    ap.add_argument("--nemo-src", default=os.environ.get("NEMO_SRC", "../nemo"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                 "upstream-gsettings.txt"))
    args = ap.parse_args()

    # Only the schemas this skin is allowed to touch; adding a schema here is a
    # deliberate widening of what the profile may write.
    wanted_prefixes = (
        "org.cinnamon", "org.gnome.desktop.interface", "org.nemo",
    )
    pairs: dict[str, set[str]] = {}
    origins: list[str] = []

    patterns = [
        (os.path.join(args.schemas_dir, "*.gschema.xml"), "installed schemas"),
        (os.path.join(args.cinnamon_src, "data", "*.gschema.xml"), "cinnamon checkout"),
        (os.path.join(args.cinnamon_src, "data", "*.gschema.xml.in"), "cinnamon checkout"),
        (os.path.join(args.cinnamon_desktop_src, "schemas", "*.gschema.xml.in"),
         "cinnamon-desktop checkout"),
        (os.path.join(args.cinnamon_desktop_src, "schemas", "*.gschema.xml"),
         "cinnamon-desktop checkout"),
        (os.path.join(args.nemo_src, "libnemo-private", "*.gschema.xml"), "nemo checkout"),
    ]
    for pattern, label in patterns:
        for path in sorted(glob.glob(pattern)):
            found = schemas_from_xml(path)
            found = {s: k for s, k in found.items()
                     if s.startswith(wanted_prefixes)}
            if not found:
                continue
            merge(pairs, found)
            if label not in origins:
                origins.append(label)

    if not pairs:
        print(f"no gschema found (looked in {args.schemas_dir} and the source dirs) — "
              "nothing written, committed allowlist stays in force", file=sys.stderr)
        return 1

    ids = sorted(pairs)
    lines = [
        "# GENERATED by tools/gen-gsettings.py — do not edit by hand.",
        "# schema<TAB>key pairs that a real Cinnamon/GTK stack defines, so a profile",
        "# line that no schema owns (invented, renamed, or dropped upstream) is an error",
        "# instead of a silent no-op in dconf.",
        f"# sources: {', '.join(origins)}",
        f"# schemas: {len(ids)}   keys: {sum(len(pairs[s]) for s in ids)}",
        "#",
    ]
    for sid in ids:
        for key in sorted(pairs[sid]):
            lines.append(f"{sid}\t{key}")
    open(args.out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"{args.out}: {sum(len(pairs[s]) for s in ids)} (schema, key) pairs "
          f"from {len(ids)} schemas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
