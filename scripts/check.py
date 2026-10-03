#!/usr/bin/env python3
"""Check a language pack's Waybar module overrides against a HyDE checkout.

    scripts/check.py <pack dir> <HyDE checkout>

A pack overrides a module by shipping a partial copy of it under
`<pack>/waybar/modules/`. Waybar merges include files that define the same
module key and the first one loaded wins on a conflict, so a pack only has to
carry the keys it translates. This script keeps that safe:

- only `.jsonc` modules (see the note in main());
- every file, module and key must exist in HyDE's own module (no typos that
  silently do nothing, no new modules);
- only text keys may be overridden (`format*`, `tooltip-format*`); a pack can
  never replace `exec`, `on-click`, `menu-actions` and the like, since a pack
  is third-party content that would otherwise run commands;
- a value stays a string and keeps the same `{placeholders}` as HyDE's, so a
  translation cannot drop `{percent}` or add one Waybar does not fill.

A bash catalog (`<pack>/<lang>.sh`) is sourced by HyDE's l10n.sh, so it may hold
only `_T["key"]="value"` lines, with no `$`, backtick, backslash or quote inside,
and never the key "HyDE Alert" (a dunst rule matches that notification app name).
A wlogout layout (`<pack>/wlogout/layout_*`) is shipped whole; only each entry's
"text" may differ, never its label, action or keybind.

A menu (`<pack>/waybar/menus/*.xml`) cannot be merged, so a pack ships the whole
file; the check makes sure only the label text differs. The tree must be the
same as HyDE's (same elements, ids and classes, in the same order), because a
menu item's id is what a module's `menu-actions` key points at. Only a
`label` property may change, and it keeps its leading icon glyph.

Exit status: 0 clean, 1 findings, 2 usage or unreadable input.
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MODULES = Path("Configs/.local/share/waybar/modules")
MENUS = Path("Configs/.local/share/waybar/menus")
WLOGOUT = Path("Configs/.config/wlogout")
# A bash catalog is sourced by l10n.sh, so it is code: only this exact line shape
# is accepted. No $, backtick, backslash or quote can appear inside, which is what
# keeps a value from running a command or ending its own string.
CATALOG_LINE = re.compile(r'^_T\["([^"$`\\\r\n]+)"\]="([^"$`\\\r\n]+)"$')
# Keys a pack may not translate: dunstrc matches this notification app name.
RESERVED_KEYS = {"HyDE Alert"}
# The only keys a pack may override: the text Waybar shows.
TEXT_KEY = re.compile(r"^(format|tooltip-format)(-[A-Za-z0-9_-]+)?$")
PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def strip_comments(text: str) -> str:
    """Drop // and /* */ comments, leaving string contents (and URLs) alone."""
    out, i, n = [], 0, len(text)
    in_string = False
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
            out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def load(path: Path):
    text = path.read_text(encoding="utf-8-sig")
    text = strip_comments(text)
    # Waybar tolerates trailing commas in .jsonc; strict JSON does not.
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return json.loads(text)


def check_file(pack_file: Path, upstream_file: Path) -> list[str]:
    findings: list[str] = []
    name = pack_file.name
    try:
        pack = load(pack_file)
    except (ValueError, OSError) as e:
        return [f"{name}: cannot be read ({e})"]
    try:
        upstream = load(upstream_file)
    except (ValueError, OSError) as e:
        return [f"{name}: HyDE's module cannot be read ({e})"]

    if not isinstance(pack, dict):
        return [f"{name}: top level must be an object, got {type(pack).__name__}"]

    for module, body in pack.items():
        if module not in upstream:
            findings.append(f"{name}: module '{module}' does not exist in HyDE's {name}")
            continue
        if not isinstance(body, dict):
            findings.append(f"{name}: module '{module}' must be an object")
            continue
        for key, value in body.items():
            where = f"{name}: {module}.{key}"
            if not TEXT_KEY.match(key):
                findings.append(f"{where}: not a text key, a pack may only override format* and tooltip-format*")
                continue
            if key not in upstream[module]:
                findings.append(f"{where}: HyDE's module has no such key")
                continue
            original = upstream[module][key]
            if not isinstance(value, str) or not isinstance(original, str):
                findings.append(f"{where}: must be a string like HyDE's")
                continue
            have, want = sorted(PLACEHOLDER.findall(value)), sorted(PLACEHOLDER.findall(original))
            if have != want:
                findings.append(f"{where}: placeholders {have} differ from HyDE's {want}")
    return findings


def _glyph_prefix(text: str) -> str:
    """The leading icon glyph and its spacing, e.g. "\U000f0335\u2003"."""
    m = re.match(r"^[^\x00-\x7f\u2003\s]+[\s\u2003]*", text or "")
    return m.group(0) if m else ""


def _same_tree(pack: ET.Element, upstream: ET.Element, path: str, findings: list[str]) -> None:
    if pack.tag != upstream.tag or pack.attrib != upstream.attrib:
        findings.append(f"{path}: <{pack.tag} {pack.attrib}> differs from HyDE's <{upstream.tag} {upstream.attrib}>")
        return
    if pack.tag == "property" and pack.get("name") == "label":
        text, original = pack.text or "", upstream.text or ""
        if not text.strip():
            findings.append(f"{path}: label is empty")
        elif not text[len(_glyph_prefix(text)):].strip():
            findings.append(f"{path}: label has an icon but no text, so it is empty")
        if _glyph_prefix(text) != _glyph_prefix(original):
            findings.append(f"{path}: label must keep HyDE's leading icon {_glyph_prefix(original)!r}")
        return
    if (pack.text or "").strip() != (upstream.text or "").strip():
        findings.append(f"{path}: text differs, only label properties may change")
    if len(pack) != len(upstream):
        findings.append(f"{path}: has {len(pack)} children, HyDE's has {len(upstream)}")
        return
    for index, (a, b) in enumerate(zip(pack, upstream)):
        name = b.get("id") or b.get("name") or b.tag
        _same_tree(a, b, f"{path}/{name}[{index}]", findings)


def check_menu(pack_file: Path, upstream_file: Path) -> list[str]:
    name = pack_file.name
    try:
        raw = pack_file.read_bytes()
    except OSError as e:
        return [f"{name}: cannot be read ({e})"]
    # A menu never needs a DTD; refusing it closes entity-expansion tricks.
    if re.search(rb"<!(DOCTYPE|ENTITY)", raw, re.I):
        return [f"{name}: DOCTYPE and ENTITY declarations are not allowed"]
    try:
        pack = ET.fromstring(raw)
        upstream = ET.parse(upstream_file).getroot()
    except (ET.ParseError, OSError) as e:
        return [f"{name}: cannot be read ({e})"]
    findings: list[str] = []
    _same_tree(pack, upstream, name, findings)
    return findings


def check_catalog(pack_file: Path) -> list[str]:
    name = pack_file.name
    try:
        text = pack_file.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return [f"{name}: cannot be read ({e})"]
    if re.search(r"[\x00-\x08\x0b-\x1f\x7f]", text):
        return [f"{name}: control characters are not allowed"]
    findings: list[str] = []
    seen: set[str] = set()
    for number, line in enumerate(text.split("\n"), start=1):
        if not line.strip() or line.lstrip().startswith("#") and "\r" not in line:
            continue
        m = CATALOG_LINE.match(line)
        if not m:
            findings.append(f"{name}:{number}: not a plain _T[\"key\"]=\"value\" line (the file is sourced as shell code)")
            continue
        key, value = m.groups()
        if key in RESERVED_KEYS:
            findings.append(f"{name}:{number}: '{key}' must not be translated (a dunst rule matches it)")
        if key in seen:
            findings.append(f"{name}:{number}: duplicate key '{key}'")
        seen.add(key)
        if not value.strip():
            findings.append(f"{name}:{number}: empty value for '{key}'")
    return findings


def _json_objects(text: str) -> list:
    """wlogout layouts are objects written one after another, not an array."""
    decoder, objects, i = json.JSONDecoder(), [], 0
    while True:
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            return objects
        obj, i = decoder.raw_decode(text, i)
        objects.append(obj)


def check_wlogout(pack_file: Path, upstream_file: Path) -> list[str]:
    name = pack_file.name
    try:
        pack = _json_objects(pack_file.read_text(encoding="utf-8-sig"))
        upstream = _json_objects(upstream_file.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as e:
        return [f"{name}: cannot be read ({e})"]
    if len(pack) != len(upstream):
        return [f"{name}: has {len(pack)} entries, HyDE's has {len(upstream)}"]
    findings: list[str] = []
    for index, (a, b) in enumerate(zip(pack, upstream)):
        label = b.get("label", index) if isinstance(b, dict) else index
        if not isinstance(a, dict) or not isinstance(b, dict) or set(a) != set(b):
            findings.append(f"{name}: entry '{label}' has different keys than HyDE's")
            continue
        for key in b:
            if key == "text":
                if not isinstance(a[key], str) or not a[key].strip():
                    findings.append(f"{name}: entry '{label}' text must be a non-empty string")
            elif a[key] != b[key]:
                findings.append(f"{name}: entry '{label}' changes '{key}', only 'text' may differ")
    return findings


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    pack, hyde = Path(argv[1]), Path(argv[2])
    pack_modules = pack / "waybar" / "modules"
    hyde_modules = hyde / MODULES
    if not any(p.is_dir() for p in (pack_modules, pack / "waybar" / "menus", pack / "wlogout")) and not list(pack.glob("*.sh")):
        print(f"nothing to check in {pack}", file=sys.stderr)
        return 2
    if not hyde_modules.is_dir():
        print(f"{hyde} is not a HyDE checkout (no {MODULES})", file=sys.stderr)
        return 2

    findings: list[str] = []
    module_files = sorted(p for p in pack_modules.iterdir() if p.is_file()) if pack_modules.is_dir() else []
    for pack_file in module_files:
        # HyDE's update_icon_size() copies *.json modules into includes.json and
        # replaces a module as a whole there, which is not how Waybar merges
        # includes, so a partial override of one would be lost. Only .jsonc until
        # that is settled.
        if pack_file.suffix != ".jsonc":
            findings.append(f"{pack_file.name}: only .jsonc module overrides are supported for now")
            continue
        upstream_file = hyde_modules / pack_file.name
        if not upstream_file.is_file():
            findings.append(f"{pack_file.name}: HyDE has no such module file")
            continue
        findings.extend(check_file(pack_file, upstream_file))

    for catalog in sorted(pack.glob("*.sh")):
        findings.extend(check_catalog(catalog))

    pack_wlogout = pack / "wlogout"
    if pack_wlogout.is_dir():
        for pack_file in sorted(p for p in pack_wlogout.iterdir() if p.is_file()):
            upstream_file = hyde / WLOGOUT / pack_file.name
            if not upstream_file.is_file():
                findings.append(f"{pack_file.name}: HyDE has no such wlogout file")
                continue
            findings.extend(check_wlogout(pack_file, upstream_file))

    pack_menus = pack / "waybar" / "menus"
    if pack_menus.is_dir():
        for pack_file in sorted(pack_menus.glob("*.xml")):
            upstream_file = hyde / MENUS / pack_file.name
            if not upstream_file.is_file():
                findings.append(f"{pack_file.name}: HyDE has no such menu")
                continue
            findings.extend(check_menu(pack_file, upstream_file))

    for line in findings:
        print(line)
    print(f"{len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
