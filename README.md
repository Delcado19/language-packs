# language-packs

Language packs for HyDE: translated text that is installed next to HyDE and removed again without touching it. HyDE's own files stay untouched; a pack only adds files.

> **Status: draft.** The packs and their installer work (see below). Two parts already work with HyDE as it is: the bash catalog (`<lang>.sh`, read by `l10n.sh`). The Waybar modules, menus and wlogout layouts need HyDE to look in a `locale` layer first (a lookup in `waybar.py` and `logoutlaunch.sh`). This repository is here to settle the format before that change is made.

## What is in a pack

```
de/                         # a pack: one folder per language
  waybar/modules/
    backlight.jsonc         # a partial copy of HyDE's module, only the text
    ...                     # 25 module files in all
  waybar/menus/
    power.xml               # a whole copy of HyDE's menu with translated labels
    ...                     # 10 menus in all
us/                         # the reference template: same files, HyDE's own English
  de.sh                     # bash catalog for l10n.sh: _T["English"]="Deutsch"
  wlogout/layout_1          # a whole copy of HyDE's wlogout layout, "text" translated
  wlogout/layout_2
language-pack-de.toml       # deez-dots file that installs de/
language-pack-us.toml
scripts/check.py            # keeps a pack to translating
tests/test_check.py
```

A file under `<pack>/waybar/modules/` mirrors the path of HyDE's module and carries **only the keys it translates**:

```jsonc
// de/waybar/modules/backlight.jsonc
{
  "backlight": {
    "tooltip-format": "Helligkeit: {icon} {percent}%"
  }
}
```

`us/` is the template to copy for a new language: every translatable string of the modules, as HyDE ships it.

## Bash catalog

`l10n.sh` already loads `${XDG_DATA_HOME}/hyde/locale/<lang>.sh` and uses it for `cliphist.sh` (`_T[...]`) and, through `send_notifs`, for `screenshot.sh`. `de.sh` ships the 49 strings those two scripts pass. Nothing in HyDE has to change; installing the pack is enough. Checked with HyDE's own `l10n.sh` against an installed pack: `_T[Deleted]` is `Gelöscht`, `send_notifs "Screenshot Error" …` shows the German text, and another language simply falls back to English.

Two things about this file:

- **It is code.** `l10n.sh` `source`s it. The checker therefore accepts nothing but `_T["key"]="value"` lines, with no `$`, backtick, backslash or quote inside, no control characters, no CRLF and no duplicate key. A catalog that passes cannot run a command when sourced; a test sources one with real bash to prove it.
- **Never translate `HyDE Alert`.** `send_notifs` translates every argument that does not start with `-`, including the app name after `-a`, and `dunstrc` matches `appname = "HyDE Alert"`. The checker refuses that key. (HyDE itself should leave the arguments of `-a`, `-i` and `-r` alone; that is a small fix in `l10n.sh`, not in a pack.)
- A message with a value in it, like `saved in $save_dir`, cannot be a key, because the script builds the string before it is translated.

## wlogout

`~/.config/wlogout/layout_1` and `layout_2` hold the six logout actions as objects with `label`, `action`, `text` and `keybind`. A pack ships the whole file; the checker allows only `text` to differ. A changed `label`, `action` or `keybind` is refused: an action is a command, and a keybind is muscle memory (the letter stays even where the German word starts with another). `us/wlogout` is HyDE's own file.

## Not in a pack yet

Text that scripts print themselves: `weather.py` (headings such as "Feels like", "Weather unavailable"), `mediaplayer.py` and `gpuinfo.sh` ("Temperature:", "Utilization:", "Clock Speed:", "Fan Speed:", "Suspended mode"). None of them calls a catalog today (`gpuinfo.sh` and the Python scripts do not source `l10n.sh`; Python has no `gettext`), so there is nothing a pack could translate. They need the script-side work from the issue (`.pot` for Python, a hashmap for bash) first.

## Menus

A Waybar menu (`menus/*.xml`) has no keys a merge could fill in, so a pack ships the **whole file**. Everything but the label text must stay as it is in HyDE: a menu item's `id` is what a module's `menu-actions` key points at, so an item that is renamed, added or dropped would stop working or do nothing.

```xml
<!-- de/waybar/menus/power.xml -->
<object class="GtkMenuItem" id="lock">
    <property name="label">󰍁  Sperren</property>
</object>
```

`scripts/check.py` compares the pack's tree with HyDE's, element by element: same tags, ids and classes in the same order, and only `label` properties may differ. A label keeps its leading icon and must still have text. DOCTYPE and ENTITY declarations are refused (a menu never needs them, and a pack is third-party XML).

The price of a whole file is that it goes stale when HyDE changes the menu. The checker and the test that compares `us/` with HyDE's menus catch that when run against a HyDE checkout.

## How it is applied

A pack installs to `${XDG_DATA_HOME}/hyde/locale/<lang>/` (modules, menus, wlogout) and its catalog to `${XDG_DATA_HOME}/hyde/locale/<lang>.sh`, the place `l10n.sh` already reads from. Waybar then merges the include files that define the same module.

I checked how Waybar (0.15.0, `waybar-git`) merges them: **a key defined in the file loaded first wins, and keys the first file lacks are filled in from later files.** So a partial override is enough and the module keeps everything else from HyDE. The layers, strongest first:

```
user      ~/.config/waybar/modules
locale    ~/.local/share/hyde/locale/<lang>/waybar/modules     (new)
hyde      ~/.local/share/waybar/modules
```

Menus have no merge, so for them the locale layer is a per-file choice: use `~/.local/share/hyde/locale/<lang>/waybar/menus/<file>` when it exists, else HyDE's own. Modules point at `${HYDE_WAYBAR_MENU_DIR:-$XDG_DATA_HOME/waybar/menus}/<file>`, so this is a lookup in HyDE, not something a pack can do alone.

That is the existing `hyde > user` order with one layer between. Nested objects (`calendar.format`) and arrays (`format-icons`) were not tested for merging, which is why a pack may not override them yet (see the rules). `.json` modules are left out too: HyDE's `update_icon_size()` copies those into `includes.json` and replaces a module as a whole there, which is not the merge described above.

## Install and remove

With [deez-dots](https://github.com/HyDE-Project/deez-dots):

```sh
deez dots --config language-pack-de.toml --source . --deploy language-pack-de
deez dots --config language-pack-de.toml --source . --uninstall language-pack-de
```

Deploying twice is a no-op (the content hash matches), uninstalling removes exactly the files the pack installed and leaves other packs alone, and uninstalling a pack that is not installed is skipped. deez keeps a backup archive of what it removes. I ran all of this against a temporary home.

## Rules for a pack

`scripts/check.py` enforces them, and the tests feed it hostile and malformed packs:

1. **Only `.jsonc` modules, and only text keys**: `format*` and `tooltip-format*`. A pack is third-party content; overriding `exec`, `on-click` or `menu-actions` would let it run commands.
2. **Only keys that exist** in HyDE's module (a typo would silently do nothing), in a module file that exists.
3. **Strings stay strings, and keep the same `{placeholders}`** as HyDE's, so a translation cannot drop `{percent}` or add one Waybar does not fill.
4. **No nested objects** for now.
5. Icon glyphs stay as `\uXXXX` escapes in module files (a typed glyph can come out blank); letters stay readable. In menu XML the glyphs are copied from HyDE's file as they are.
6. Menus: same tree as HyDE's, only labels change, no DOCTYPE or ENTITY.
7. Catalog: plain `_T["key"]="value"` lines only, never the key `HyDE Alert`.
8. wlogout: only `text` changes.

```sh
python3 scripts/check.py de /path/to/HyDE
HYDE_CHECKOUT=/path/to/HyDE python3 -m unittest discover -s tests
```

## Add a language

Copy `us/` to `<lang>/`, translate the strings, copy a `language-pack-<lang>.toml`, and run `check.py`. Translate only what you can verify; the `de` pack is the reference for a translated pack, and the other languages come from whoever speaks them.
