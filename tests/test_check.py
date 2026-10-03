"""Run: python3 -m unittest discover -s tests

check.py is what keeps a third-party pack from doing more than translating, so
the cases below are mostly inputs a careless or hostile pack might contain.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "check.py"
UPSTREAM = """{
  // a comment, and a URL in a string: "https://example.org//x"
  "backlight": {
    "format": "{icon} {percent}%",
    "tooltip-format": "Backlight level: {icon} {percent}%",
    "on-scroll-up": "hyde-shell brightnesscontrol i 1",
    "min-length": 6,
    "calendar": { "format": { "today": "<b>{}</b>" } },
  },
  "custom/x": { "tooltip-format": "Hello" }
}
"""


class Checker(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.hyde = self.tmp / "hyde"
        mods = self.hyde / "Configs/.local/share/waybar/modules"
        mods.mkdir(parents=True)
        (mods / "backlight.jsonc").write_text(UPSTREAM, encoding="utf-8")
        self.pack = self.tmp / "pack"
        (self.pack / "waybar/modules").mkdir(parents=True)

    def run_check(self, content=None, name="backlight.jsonc", raw=None):
        path = self.pack / "waybar/modules" / name
        if raw is not None:
            path.write_bytes(raw)
        elif content is not None:
            path.write_text(content, encoding="utf-8")
        done = subprocess.run(
            [sys.executable, str(CHECK), str(self.pack), str(self.hyde)],
            capture_output=True,
            text=True,
        )
        return done.returncode, done.stdout + done.stderr

    def assertFails(self, out, needle):
        code, text = out
        self.assertEqual(code, 1, text)
        self.assertIn(needle, text)

    # ---- accepted ----
    def test_a_translation_passes(self):
        code, text = self.run_check('{"backlight": {"tooltip-format": "Helligkeit: {icon} {percent}%"}}')
        self.assertEqual(code, 0, text)

    def test_comments_and_trailing_commas_pass(self):
        code, text = self.run_check(
            '// header\n{ /* x */ "backlight": { "tooltip-format": "H {icon} {percent}%", }, }\n'
        )
        self.assertEqual(code, 0, text)

    def test_only_jsonc_overrides_are_accepted(self):
        (self.hyde / "Configs/.local/share/waybar/modules/tray.json").write_text('{"tray": {"format": "x"}}')
        self.assertFails(self.run_check('{"tray": {"format": "y"}}', name="tray.json"), "only .jsonc")
        self.assertFails(self.run_check("{}", name="notes.txt"), "only .jsonc")
        self.assertFails(self.run_check("{}", name="backlight.JSONC"), "only .jsonc")

    def test_empty_object_and_empty_pack_pass(self):
        self.assertEqual(self.run_check("{}")[0], 0)

    def test_utf8_bom_and_umlauts_pass(self):
        raw = b'\xef\xbb\xbf{"backlight": {"tooltip-format": "H\xc3\xa4lligkeit {icon} {percent}%"}}'
        self.assertEqual(self.run_check(raw=raw)[0], 0)

    def test_placeholder_order_may_change(self):
        out = self.run_check('{"backlight": {"tooltip-format": "{percent}% {icon}"}}')
        self.assertEqual(out[0], 0, out[1])

    # ---- refused ----
    def test_command_keys_are_never_overridable(self):
        for key in ("on-scroll-up", "exec", "on-click", "menu-actions", "min-length"):
            with self.subTest(key=key):
                self.assertFails(
                    self.run_check('{"backlight": {"%s": "x"}}' % key), "not a text key"
                )

    def test_key_that_only_looks_like_a_text_key(self):
        for key in ("formatted", "tooltip", "format ", "Format", "tooltip-format;rm"):
            with self.subTest(key=key):
                self.assertFails(self.run_check('{"backlight": {"%s": "x"}}' % key), "not a text key")

    def test_unknown_key_module_and_file(self):
        self.assertFails(self.run_check('{"backlight": {"format-alt": "x"}}'), "no such key")
        self.assertFails(self.run_check('{"nope": {"format": "x"}}'), "does not exist")
        self.assertFails(self.run_check('{"a": {}}', name="nothere.jsonc"), "no such module file")

    def test_dropped_or_added_placeholder(self):
        self.assertFails(self.run_check('{"backlight": {"tooltip-format": "Helligkeit {icon}"}}'), "placeholders")
        self.assertFails(self.run_check('{"backlight": {"tooltip-format": "{icon} {percent}% {extra}"}}'), "placeholders")
        self.assertFails(self.run_check('{"backlight": {"tooltip-format": "no placeholders"}}'), "placeholders")

    def test_wrong_types(self):
        for value in ('["a"]', "5", "null", "true", '{"a": "b"}'):
            with self.subTest(value=value):
                self.assertFails(self.run_check('{"backlight": {"tooltip-format": %s}}' % value), "must be a string")

    def test_nested_objects_are_refused(self):
        self.assertFails(self.run_check('{"backlight": {"calendar": {"format": {"today": "x"}}}}'), "not a text key")

    def test_module_must_be_an_object(self):
        self.assertFails(self.run_check('{"backlight": "x"}'), "must be an object")
        self.assertFails(self.run_check('{"backlight": null}'), "must be an object")

    def test_garbage_files(self):
        self.assertFails(self.run_check("not json"), "cannot be read")
        self.assertFails(self.run_check(""), "cannot be read")
        self.assertFails(self.run_check("[1, 2]"), "top level must be an object")
        self.assertFails(self.run_check(raw=b"\xff\xfe\x00{"), "cannot be read")

    def test_unterminated_comment_does_not_hang(self):
        # The run finishing at all is the point; an open comment is dropped to the end.
        code, _ = self.run_check('{"backlight": {"tooltip-format": "{icon} {percent}%"}} /* open')
        self.assertIn(code, (0, 1))

    # ---- usage ----
    def test_bad_arguments_and_missing_dirs(self):
        bad = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        no_pack = subprocess.run(
            [sys.executable, str(CHECK), str(self.tmp / "missing"), str(self.hyde)], capture_output=True, text=True
        )
        self.assertEqual(no_pack.returncode, 2)
        no_hyde = subprocess.run(
            [sys.executable, str(CHECK), str(self.pack), str(self.tmp / "missing")], capture_output=True, text=True
        )
        self.assertEqual(no_hyde.returncode, 2)


MENU = """<?xml version="1.0" encoding="UTF-8"?>
<interface>
  <object class="GtkMenu" id="menu">
    <child>
      <object class="GtkMenuItem" id="lock">
        <property name="label">\U000f0341\u2003Lock</property>
      </object>
    </child>
    <child>
      <object class="GtkMenuItem" id="logout">
        <property name="label">\U000f0343  Logout</property>
      </object>
    </child>
  </object>
</interface>
"""


class Menus(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.hyde = self.tmp / "hyde"
        menus = self.hyde / "Configs/.local/share/waybar/menus"
        menus.mkdir(parents=True)
        (self.hyde / "Configs/.local/share/waybar/modules").mkdir(parents=True)
        (menus / "power.xml").write_text(MENU, encoding="utf-8")
        self.pack = self.tmp / "pack"
        (self.pack / "waybar/menus").mkdir(parents=True)

    def run_check(self, content=None, raw=None, name="power.xml"):
        path = self.pack / "waybar/menus" / name
        if raw is not None:
            path.write_bytes(raw)
        else:
            path.write_text(content, encoding="utf-8")
        done = subprocess.run(
            [sys.executable, str(CHECK), str(self.pack), str(self.hyde)], capture_output=True, text=True
        )
        return done.returncode, done.stdout + done.stderr

    def assertFails(self, out, needle):
        self.assertEqual(out[0], 1, out[1])
        self.assertIn(needle, out[1])

    def edit(self, old, new, count=1):
        return MENU.replace(old, new, count)

    def test_a_translation_passes(self):
        out = self.run_check(self.edit("Lock<", "Sperren<").replace("Logout", "Abmelden"))
        self.assertEqual(out[0], 0, out[1])

    def test_identical_copy_passes_and_whitespace_may_differ(self):
        self.assertEqual(self.run_check(MENU)[0], 0)
        self.assertEqual(self.run_check(MENU.replace("\n    <child>", "\n\n        <child>"))[0], 0)

    def test_changed_id_class_or_property_name_is_refused(self):
        self.assertFails(self.run_check(self.edit('id="lock"', 'id="lokk"')), "differs from HyDE's")
        self.assertFails(self.run_check(self.edit('class="GtkMenuItem"', 'class="GtkImageMenuItem"')), "differs")
        self.assertFails(self.run_check(self.edit('name="label"', 'name="tooltip-text"')), "differs")

    def test_added_removed_or_reordered_items_are_refused(self):
        extra = '<child><object class="GtkMenuItem" id="evil"><property name="label">\U000f0341 x</property></object></child>'
        self.assertFails(self.run_check(self.edit("</object>\n</interface>", extra + "</object>\n</interface>")), "children")
        one = MENU.split("    <child>")
        self.assertFails(self.run_check(one[0] + "    <child>" + one[1] + "  </object>\n</interface>\n"), "children")
        swapped = MENU.replace('id="lock"', "TMP").replace('id="logout"', 'id="lock"').replace("TMP", 'id="logout"')
        self.assertFails(self.run_check(swapped), "differs")

    def test_other_properties_cannot_change(self):
        with_prop = MENU.replace("</object>\n    </child>", '<property name="tooltip-text">x</property></object>\n    </child>', 1)
        self.assertFails(self.run_check(with_prop), "children")

    def test_text_outside_a_label_cannot_change(self):
        self.assertFails(self.run_check(self.edit("<child>", "<child>injected", 1)), "text differs")
        self.assertFails(self.run_check(self.edit('<object class="GtkMenu" id="menu">', '<object class="GtkMenu" id="menu">x')), "text differs")

    def test_label_must_keep_its_icon_and_not_be_empty(self):
        self.assertFails(self.run_check(self.edit("\U000f0341\u2003Lock", "Sperren")), "leading icon")
        self.assertFails(self.run_check(self.edit("\U000f0341\u2003Lock", "\U000f0343\u2003Sperren")), "leading icon")
        self.assertFails(self.run_check(self.edit("\U000f0341\u2003Lock", "\U000f0341\u2003")), "is empty")
        self.assertFails(self.run_check(self.edit("\U000f0341\u2003Lock", "")), "label is empty")

    def test_doctype_and_entities_are_refused(self):
        bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>' + MENU.split("?>", 1)[1]
        self.assertFails(self.run_check(bomb), "not allowed")
        self.assertFails(self.run_check(self.edit("<interface>", "<!doctype x><interface>")), "not allowed")

    def test_garbage_files(self):
        self.assertFails(self.run_check("not xml"), "cannot be read")
        self.assertFails(self.run_check(""), "cannot be read")
        self.assertFails(self.run_check(raw=b"\xff\xfe<"), "cannot be read")
        self.assertFails(self.run_check(MENU[:-20]), "cannot be read")

    def test_unknown_menu_file(self):
        self.assertFails(self.run_check(MENU, name="nope.xml"), "no such menu")


class Catalogs(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.hyde = self.tmp / "hyde"
        (self.hyde / "Configs/.local/share/waybar/modules").mkdir(parents=True)
        self.pack = self.tmp / "pack"
        self.pack.mkdir()

    def run_check(self, content=None, raw=None):
        path = self.pack / "de.sh"
        if raw is not None:
            path.write_bytes(raw)
        else:
            path.write_text(content, encoding="utf-8")
        done = subprocess.run(
            [sys.executable, str(CHECK), str(self.pack), str(self.hyde)], capture_output=True, text=True
        )
        return done.returncode, done.stdout + done.stderr

    def assertFails(self, out, needle=""):
        self.assertEqual(out[0], 1, out[1])
        self.assertIn(needle, out[1])

    def test_plain_lines_comments_and_blanks_pass(self):
        out = self.run_check('# a comment\n\n_T["Deleted"]="Gelöscht"\n_T["Yes"]="Ja"\n')
        self.assertEqual(out[0], 0, out[1])

    def test_empty_file_and_comments_only_pass(self):
        self.assertEqual(self.run_check("")[0], 0)
        self.assertEqual(self.run_check("# nothing\n")[0], 0)

    def test_characters_that_are_only_text_pass(self):
        for value in ("a; b", "a & b", "a | b", "a < b > c", "*?[x]{y}", "100%", "it's", "~/x", "#1", "!bang", "ä ö ü ß", "日本語"):
            with self.subTest(value=value):
                self.assertEqual(self.run_check('_T["k"]="%s"\n' % value)[0], 0)

    def test_command_substitution_and_expansion_are_refused(self):
        for value in ("$(touch /tmp/pwn)", "`touch /tmp/pwn`", "${HOME}", "$HOME", "a$b", "\\x", "a\\\"b"):
            with self.subTest(value=value):
                self.assertFails(self.run_check('_T["k"]="%s"\n' % value), "plain")
                self.assertFails(self.run_check('_T["%s"]="v"\n' % value), "plain")

    def test_breaking_out_of_the_string_is_refused(self):
        self.assertFails(self.run_check('_T["k"]="x"; touch /tmp/pwn; "y"\n'), "plain")
        self.assertFails(self.run_check('_T["k"]="x" ; evil\n'), "plain")
        self.assertFails(self.run_check('_T["k"]="x" # c\n'), "plain")
        self.assertFails(self.run_check('_T["k"]="x"\n_T["j"]="y" && evil\n'), "plain")

    def test_other_shell_code_is_refused(self):
        for line in ("source /tmp/x", "eval x", "declare -A _T", "_T+=([a]=b)", '_T["a"]+="b"', "touch /tmp/pwn", 'x=1', '_T[a]="b"', '  _T["a"]="b"', 'export _T', '_T["a"]=b'):
            with self.subTest(line=line):
                self.assertFails(self.run_check(line + "\n"), "plain")

    def test_line_continuations_cannot_hide_code(self):
        self.assertFails(self.run_check('_T["k"]="x\\\ny"\n'), "plain")
        self.assertFails(self.run_check('_T["k"]="x"\\\n; evil\n'), "plain")

    def test_reserved_duplicate_and_empty(self):
        self.assertFails(self.run_check('_T["HyDE Alert"]="HyDE-Hinweis"\n'), "must not be translated")
        self.assertFails(self.run_check('_T["a"]="b"\n_T["a"]="c"\n'), "duplicate")
        self.assertFails(self.run_check('_T[""]="b"\n'), "plain")
        self.assertFails(self.run_check('_T["a"]=""\n'), "plain")
        self.assertFails(self.run_check('_T["a"]="   "\n'), "empty value")

    def test_crlf_bom_binary_and_control_characters(self):
        self.assertFails(self.run_check('_T["a"]="b"\r\n'), "")
        self.assertFails(self.run_check(raw=b'\xef\xbb\xbf_T["a"]="b"\n'), "plain")
        self.assertFails(self.run_check(raw=b'_T["a"]="b\x00"\n'), "control")
        self.assertFails(self.run_check(raw=b'_T["a"]="b\x1b[31m"\n'), "control")
        self.assertFails(self.run_check(raw=b'\xff\xfe_T'), "cannot be read")

    def test_very_long_value_is_fine(self):
        self.assertEqual(self.run_check('_T["k"]="%s"\n' % ("x" * 50000))[0], 0)

    def test_accepted_catalog_really_only_assigns(self):
        """What passes the check, sourced by real bash, only fills _T."""
        import shutil

        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash is not installed")
        marker = self.tmp / "pwned"
        values = ["a; touch %s" % marker, "a & b | c", "*?[x]{y}", "it's", "!bang", "~", "#1", "a\tb"]
        body = "".join('_T["k%d"]="%s"\n' % (i, v) for i, v in enumerate(values))
        self.assertEqual(self.run_check(body)[0], 0)
        script = 'declare -A _T; source "%s"; for k in "${!_T[@]}"; do printf "%%s=%%s\\n" "$k" "${_T[$k]}"; done' % (self.pack / "de.sh")
        done = subprocess.run([bash, "-c", script], capture_output=True, text=True, cwd=self.tmp)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(marker.exists(), "sourcing the catalog ran a command")
        got = dict(line.split("=", 1) for line in done.stdout.splitlines())
        self.assertEqual(got["k0"], values[0])


LAYOUT = """{
    "label": "lock",
    "action": "lockscreen.sh",
    "text": "Lock",
    "keybind": "l"
}

{
    "label": "logout",
    "action": "hyde-shell logout",
    "text": "Logout",
    "keybind": "e"
}
"""


class Wlogout(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.hyde = self.tmp / "hyde"
        (self.hyde / "Configs/.local/share/waybar/modules").mkdir(parents=True)
        wl = self.hyde / "Configs/.config/wlogout"
        wl.mkdir(parents=True)
        (wl / "layout_1").write_text(LAYOUT, encoding="utf-8")
        self.pack = self.tmp / "pack"
        (self.pack / "wlogout").mkdir(parents=True)

    def run_check(self, content=None, raw=None, name="layout_1"):
        path = self.pack / "wlogout" / name
        if raw is not None:
            path.write_bytes(raw)
        else:
            path.write_text(content, encoding="utf-8")
        done = subprocess.run(
            [sys.executable, str(CHECK), str(self.pack), str(self.hyde)], capture_output=True, text=True
        )
        return done.returncode, done.stdout + done.stderr

    def assertFails(self, out, needle=""):
        self.assertEqual(out[0], 1, out[1])
        self.assertIn(needle, out[1])

    def test_a_translation_passes(self):
        out = self.run_check(LAYOUT.replace("Lock", "Sperren").replace("Logout", "Abmelden"))
        self.assertEqual(out[0], 0, out[1])

    def test_only_text_may_change(self):
        for old, new in (('"lock"', '"lokk"'), ("lockscreen.sh", "evil.sh"), ('"l"', '"x"'), ("hyde-shell logout", "rm -rf ~")):
            with self.subTest(old=old):
                self.assertFails(self.run_check(LAYOUT.replace(old, new)), "only 'text' may differ")

    def test_keys_added_removed_or_entries_missing(self):
        self.assertFails(self.run_check(LAYOUT.replace('"keybind": "l"', '"keybind": "l", "extra": "x"')), "different keys")
        self.assertFails(self.run_check(LAYOUT.replace('    "keybind": "l"\n', "").replace('"Lock",', '"Lock"')), "different keys")
        self.assertFails(self.run_check(LAYOUT.split("\n\n")[0] + "\n"), "entries")
        self.assertFails(self.run_check(LAYOUT + LAYOUT), "entries")

    def test_text_must_be_a_non_empty_string(self):
        for value in ('""', '"   "', "5", "null", '["a"]', "true"):
            with self.subTest(value=value):
                self.assertFails(self.run_check(LAYOUT.replace('"Lock"', value)), "non-empty string")

    def test_entries_that_are_not_objects(self):
        self.assertFails(self.run_check('[1, 2]'), "")
        self.assertFails(self.run_check('"a" "b"'), "")

    def test_garbage_and_unknown_files(self):
        self.assertFails(self.run_check("not json"), "cannot be read")
        self.assertFails(self.run_check(""), "entries")
        self.assertFails(self.run_check(LAYOUT[:-10]), "cannot be read")
        self.assertFails(self.run_check(raw=b"\xff\xfe{"), "cannot be read")
        self.assertFails(self.run_check(LAYOUT, name="nope"), "no such wlogout")


class ShippedPacks(unittest.TestCase):
    """The packs in this repository pass against a HyDE checkout, when given one."""

    def test_shipped_packs(self):
        import os

        hyde = os.environ.get("HYDE_CHECKOUT")
        if not hyde:
            self.skipTest("set HYDE_CHECKOUT to a HyDE checkout")
        for lang in ("de", "us"):
            with self.subTest(lang=lang):
                done = subprocess.run(
                    [sys.executable, str(CHECK), str(ROOT / lang), hyde], capture_output=True, text=True
                )
                self.assertEqual(done.returncode, 0, done.stdout)

    def test_us_covers_every_english_text_key_of_hyde(self):
        """A text key HyDE ships in English must have an entry in the template."""
        import os
        import re

        hyde = os.environ.get("HYDE_CHECKOUT")
        if not hyde:
            self.skipTest("set HYDE_CHECKOUT to a HyDE checkout")
        sys.path.insert(0, str(ROOT / "scripts"))
        from check import MODULES, PLACEHOLDER, TEXT_KEY, load

        def has_english(value):
            text = PLACEHOLDER.sub(" ", value)
            text = re.sub(r"<[^>]*>", " ", text)
            text = re.sub(r"[^\x00-\x7f]", " ", text)
            text = re.sub(r"\\[nt]", " ", text)
            return bool(re.search(r"[A-Za-z]{3,}", text))

        us = {p.name: load(p) for p in (ROOT / "us/waybar/modules").glob("*.jsonc")}
        missing = []
        for path in sorted((Path(hyde) / MODULES).glob("*.json*")):
            for module, body in load(path).items():
                if not isinstance(body, dict):
                    continue
                for key, value in body.items():
                    if TEXT_KEY.match(key) and isinstance(value, str) and has_english(value):
                        if key not in us.get(path.name, {}).get(module, {}):
                            missing.append(f"{path.name}: {module}.{key}")
        self.assertEqual(missing, [], "text keys without a template entry")

    def test_us_menus_are_exact_copies_of_hydes(self):
        import os

        hyde = os.environ.get("HYDE_CHECKOUT")
        if not hyde:
            self.skipTest("set HYDE_CHECKOUT to a HyDE checkout")
        menus = Path(hyde) / "Configs/.local/share/waybar/menus"
        upstream = sorted(p.name for p in menus.glob("*.xml"))
        template = sorted(p.name for p in (ROOT / "us/waybar/menus").glob("*.xml"))
        self.assertEqual(template, upstream, "the template must have every menu HyDE ships")
        for name in upstream:
            self.assertEqual((ROOT / "us/waybar/menus" / name).read_bytes(), (menus / name).read_bytes(), name)
            self.assertTrue((ROOT / "de/waybar/menus" / name).is_file(), f"de lacks {name}")

    def test_catalogs_and_wlogout_cover_the_same_keys(self):
        import re

        def keys(path):
            return re.findall(r'^_T\["([^"]+)"\]=', path.read_text(encoding="utf-8"), re.M)

        self.assertEqual(sorted(keys(ROOT / "de/de.sh")), sorted(keys(ROOT / "us/us.sh")))
        self.assertEqual(sorted(p.name for p in (ROOT / "de/wlogout").iterdir()), sorted(p.name for p in (ROOT / "us/wlogout").iterdir()))

    def test_us_wlogout_is_an_exact_copy_of_hydes(self):
        import os

        hyde = os.environ.get("HYDE_CHECKOUT")
        if not hyde:
            self.skipTest("set HYDE_CHECKOUT to a HyDE checkout")
        upstream = Path(hyde) / "Configs/.config/wlogout"
        for path in sorted(upstream.glob("layout_*")):
            self.assertEqual((ROOT / "us/wlogout" / path.name).read_bytes(), path.read_bytes(), path.name)

    def test_de_and_us_cover_the_same_files_and_keys(self):
        import json
        sys.path.insert(0, str(ROOT / "scripts"))
        from check import load

        de = {p.name: load(p) for p in (ROOT / "de/waybar/modules").glob("*.jsonc")}
        us = {p.name: load(p) for p in (ROOT / "us/waybar/modules").glob("*.jsonc")}
        self.assertEqual(sorted(de), sorted(us))
        for name in de:
            self.assertEqual(json.dumps(de[name], sort_keys=True).count('"'), json.dumps(us[name], sort_keys=True).count('"'), name)
            for module in us[name]:
                self.assertEqual(sorted(de[name][module]), sorted(us[name][module]), f"{name}:{module}")


if __name__ == "__main__":
    unittest.main()
