"""Write locales/beamer.pot from the source, bring every locales/<code>.po in step, and check them.

    python3 tools/i18n_extract.py           # rewrite beamer.pot, add new strings to each .po, drop gone ones
    python3 tools/i18n_extract.py --check   # exit 1 if beamer.pot is stale or a translation breaks its {fields}
    python3 tools/i18n_extract.py --check --complete   # and on any untranslated string: before a release
    python3 tools/i18n_extract.py --review it   # write docs/i18n/it-review.html for a translator

Standard library only. Strings are found by reading the source, never by importing it, so the
tool runs anywhere, without AppKit or Qt: tr("..."), trn("...", "...", n), trc("context", "...")
and N_("...").
"""

from __future__ import annotations

import argparse
import ast
import html
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import i18n  # noqa: E402


SOURCES = ("core", "mac_app", "win_app")
LOCALES = ROOT / "locales"
TEMPLATE = LOCALES / "beamer.pot"
FIELD = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)[^{}]*\}")
HEADER = {
    "Project-Id-Version": "Beamer",
    "MIME-Version": "1.0",
    "Content-Type": "text/plain; charset=UTF-8",
    "Content-Transfer-Encoding": "8bit",
}


def source_files():
    for folder in SOURCES:
        for path in sorted((ROOT / folder).glob("*.py")):
            yield path


def _literal(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _branches(node) -> list[str]:
    """The literal strings an argument can be: tr("Put back" if out else "Leave out") is two."""
    if isinstance(node, ast.IfExp):
        return _branches(node.body) + _branches(node.orelse)
    text = _literal(node)
    return [text] if text else []


def extract(paths=None) -> dict:
    """{(context, msgid, plural): {places: [file:line, ...], notes: [...]}} for every marked string, in source order."""
    found: dict = {}
    for path in paths or source_files():
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        tree = ast.parse(text, str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            args = [_literal(arg) for arg in node.args]
            if name in ("tr", "N_") and node.args:
                keys = [(None, text, None) for text in _branches(node.args[0])]
            elif name == "trn" and len(args) >= 2 and args[0] and args[1]:
                keys = [(None, args[0], args[1])]
            elif name == "trc" and len(node.args) >= 2 and args[0]:
                keys = [(args[0], text, None) for text in _branches(node.args[1])]
            else:
                continue
            # The file, not the line: a line number would make the template stale on every edit above it.
            where = path.relative_to(ROOT).as_posix()
            note = _translator_note(lines, node.lineno)
            for key in keys:
                entry = found.setdefault(key, {"places": [], "notes": []})
                if where not in entry["places"]:
                    entry["places"].append(where)
                if note and note not in entry["notes"]:
                    entry["notes"].append(note)
    return found


def _translator_note(lines: list[str], lineno: int) -> str:
    """The "# Translators: ..." comment block ending on the line above a call, if there is one."""
    block, index = [], lineno - 2
    while index >= 0 and lines[index].strip().startswith("#"):
        block.insert(0, lines[index].strip().lstrip("#").strip())
        index -= 1
    for at, line in enumerate(block):
        if line.startswith("Translators:"):
            return " ".join([line[len("Translators:"):].strip()] + block[at + 1:])
    return ""


def _quote(text: str) -> str:
    body = text.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t")
    if "\n" not in body:
        return f'"{body}"'
    lines = body.split("\n")
    parts = [f'"{line}\\n"' for line in lines[:-1]] + ([f'"{lines[-1]}"'] if lines[-1] else [])
    return '""\n' + "\n".join(parts)


def _key(entry) -> tuple:
    return (entry.get("msgctxt"), entry["msgid"], entry.get("msgid_plural"))


def render(entries: list[dict], header: dict) -> str:
    out = ['msgid ""', 'msgstr ""']
    out += [f'"{name}: {value}\\n"' for name, value in header.items()]
    for entry in entries:
        out.append("")
        out += entry.get("comments", [])
        if entry.get("flags"):
            out.append("#, " + ", ".join(sorted(entry["flags"])))
        if entry.get("msgctxt") is not None:
            out.append("msgctxt " + _quote(entry["msgctxt"]))
        out.append("msgid " + _quote(entry["msgid"]))
        if entry.get("msgid_plural") is not None:
            out.append("msgid_plural " + _quote(entry["msgid_plural"]))
            for index, text in enumerate(entry["msgstr"]):
                out.append(f"msgstr[{index}] " + _quote(text))
        else:
            out.append("msgstr " + _quote(entry["msgstr"][0] if entry["msgstr"] else ""))
    return "\n".join(out) + "\n"


def header_of(entries: list[dict]) -> dict:
    for entry in entries:
        if entry["msgid"] == "" and "msgctxt" not in entry:
            lines = entry["msgstr"][0].split("\n") if entry["msgstr"] else []
            return dict(line.split(": ", 1) for line in lines if ": " in line)
    return {}


def plural_count(header: dict) -> int:
    match = re.search(r"nplurals\s*=\s*(\d+)", header.get("Plural-Forms", ""))
    return int(match.group(1)) if match else 2


def template_entries(found: dict) -> list[dict]:
    entries = []
    for (context, msgid, plural), seen in found.items():
        entry = {"msgid": msgid, "msgstr": ["", ""] if plural else [""], "flags": set(),
                 "comments": ["#. " + note for note in seen["notes"]] + ["#: " + " ".join(seen["places"])]}
        if "{" in msgid or (plural and "{" in plural):
            entry["flags"].add("python-brace-format")
        if context is not None:
            entry["msgctxt"] = context
        if plural is not None:
            entry["msgid_plural"] = plural
        entries.append(entry)
    return entries


def merge(template: list[dict], existing: list[dict], plurals: int) -> list[dict]:
    """The template's entries in its order, each carrying the translation and translator comments
    an existing .po already has; strings gone from the source are dropped (git keeps them)."""
    known = {_key(entry): entry for entry in existing if entry["msgid"]}
    merged = []
    for entry in template:
        old = known.get(_key(entry))
        new = dict(entry, flags=set(entry["flags"]))
        if "msgid_plural" in entry:
            new["msgstr"] = list(old["msgstr"]) if old else [""] * plurals
        else:
            new["msgstr"] = list(old["msgstr"][:1]) if old else [""]
        if old:
            notes = [line for line in old["comments"] if not line.startswith(("#:", "#."))]
            new["comments"] = notes + entry["comments"]
            new["flags"] |= old["flags"] & {"fuzzy"}
        merged.append(new)
    return merged


def problems(entries: list[dict], template: list[dict], plurals: int) -> list[str]:
    """Every missing, empty or broken translation, as one line each."""
    wanted = {_key(entry) for entry in template}
    have = {_key(entry): entry for entry in entries if entry["msgid"]}
    found = []
    for key in wanted - have.keys():
        found.append(f"missing: {key[1]!r}")
    for key in have.keys() - wanted:
        found.append(f"not in the source any more: {key[1]!r}")
    for key, entry in have.items():
        if key not in wanted:
            continue
        sources = [entry["msgid"]] + ([entry["msgid_plural"]] if "msgid_plural" in entry else [])
        fields = set().union(*(set(FIELD.findall(text)) for text in sources))
        if "msgid_plural" in entry and len(entry["msgstr"]) != plurals:
            found.append(f"wrong number of plural forms: {entry['msgid']!r}")
        for text in entry["msgstr"]:
            if not text.strip():
                found.append(f"untranslated: {entry['msgid']!r}")
                break
            if set(FIELD.findall(text)) - fields:
                found.append(f"unknown {{field}} in translation of {entry['msgid']!r}: {text!r}")
            missing = fields - set(FIELD.findall(text))
            # A singular may leave out {n} ("un computer"); nothing else may go.
            if missing - ({"n", "count"} if "msgid_plural" in entry else set()):
                found.append(f"translation of {entry['msgid']!r} drops {sorted(missing)}: {text!r}")
            try:
                text.format(**{name: "x" for name in FIELD.findall(text)})
            except (ValueError, IndexError, KeyError) as error:
                found.append(f"translation of {entry['msgid']!r} does not format ({error}): {text!r}")
    return sorted(found)


def catalogues():
    return sorted(path for path in LOCALES.glob("*.po"))


def review_page(code: str, entries: list[dict]) -> str:
    """One page a translator can read and mark up without the code: English, translation, where
    it shows, and any note for them."""
    name = i18n.LANGUAGES.get(code, code)
    rows, new = [], 0
    for entry in entries:
        if not entry["msgid"]:
            continue
        english = entry["msgid"] + (f"\n— plural —\n{entry['msgid_plural']}" if "msgid_plural" in entry else "")
        target = "\n— plural —\n".join(entry["msgstr"]) if "msgid_plural" in entry else (entry["msgstr"] or [""])[0]
        notes = [line[2:].strip() for line in entry["comments"] if line.startswith("#.") or line.startswith("# ")]
        places = " ".join(line[2:].strip() for line in entry["comments"] if line.startswith("#:"))
        context = entry.get("msgctxt") or ""
        # A "# New in <version>: awaiting ..." comment marks a string added since the translator last checked.
        fresh = any(line.startswith("# New in ") for line in entry["comments"])
        new += fresh
        rows.append(
            ("<tr class=new>" if fresh else "<tr>") + "<td class=n>{n}</td><td>{en}{ctx}</td><td lang={code}>{it}</td><td class=note>{note}<div class=where>{where}</div></td></tr>".format(
                n=len(rows) + 1, en=html.escape(english).replace("\n", "<br>"),
                ctx=f"<div class=ctx>({html.escape(context)})</div>" if context else "",
                code=code, it=html.escape(target).replace("\n", "<br>"),
                note=html.escape(" ".join(notes)), where=html.escape(places)))
    return f"""<!doctype html>
<html lang=en-GB><meta charset=utf-8><title>Beamer — {html.escape(name)} for checking</title>
<style>
body{{font:15px/1.45 -apple-system,"Segoe UI",system-ui,sans-serif;margin:2rem auto;max-width:72rem;padding:0 1rem;color:#1d1d1f}}
h1{{font-size:1.4rem}} p{{max-width:46rem}}
table{{border-collapse:collapse;width:100%}} td,th{{border-top:1px solid #ddd;padding:.45rem .6rem;vertical-align:top;text-align:left}}
th{{position:sticky;top:0;background:#fff}} td.n{{color:#888;width:2.5rem}} td:nth-child(2),td:nth-child(3){{width:36%}}
.ctx,.where{{color:#888;font-size:.8rem}} .note{{font-size:.85rem;color:#555}}
code{{background:#f3f3f3;padding:0 .2rem}} tr.new td{{background:#fff6d6}}
</style>
<h1>Beamer in {html.escape(name)} — every string, for checking</h1>
<p>Left is the English Beamer shows today; right is the {html.escape(name)} draft. Words in braces, like
<code>{{name}}</code>, are filled in by Beamer (a machine's name, a number) and must stay as they are,
though they can move within the sentence. To correct a line, quote its number with the fix, or edit
<code>locales/{code}.po</code> directly. {len(rows)} strings.{f" The {new} on a yellow background are new and not yet checked." if new else ""}</p>
<table><tr><th>#</th><th>English</th><th>{html.escape(name)}</th><th>Note · where it shows</th></tr>
{chr(10).join(rows)}
</table>
"""


def main() -> int:
    # Catalogue lines carry "…" and "→": a Windows console's legacy code page cannot print them.
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--complete", action="store_true", help="with --check: fail on any untranslated string too")
    parser.add_argument("--review", metavar="CODE")
    options = parser.parse_args()

    template = template_entries(extract())
    pot = render(template, dict(HEADER, **{"Language": "en_GB"}))
    if options.review:
        path = LOCALES / f"{options.review}.po"
        out = ROOT / "docs" / "i18n" / f"{options.review}-review.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(review_page(options.review, i18n.parse_po(path.read_text(encoding="utf-8"))), encoding="utf-8")
        print(out.relative_to(ROOT))
        return 0
    if options.check:
        # A string not yet translated shows in English, so only --complete (a release) fails on
        # one; a stale template or a translation that breaks its {fields} always fails.
        failed, pending = [], []
        if not TEMPLATE.exists() or TEMPLATE.read_text(encoding="utf-8") != pot:
            failed.append(f"{TEMPLATE.relative_to(ROOT)} is stale: run python3 tools/i18n_extract.py")
        for path in catalogues():
            entries = i18n.parse_po(path.read_text(encoding="utf-8"))
            for line in problems(entries, template, plural_count(header_of(entries))):
                soft = line.startswith(("missing:", "untranslated:", "not in the source any more:"))
                (pending if soft and not options.complete else failed).append(f"{path.relative_to(ROOT)}: {line}")
        print("\n".join(failed + pending) or f"{len(template)} strings, catalogues complete")
        if pending and not failed:
            print(f"{len(pending)} waiting for translation; they show in English until then")
        return 1 if failed else 0

    LOCALES.mkdir(exist_ok=True)
    TEMPLATE.write_text(pot, encoding="utf-8")
    for path in catalogues():
        entries = i18n.parse_po(path.read_text(encoding="utf-8"))
        header = header_of(entries)
        path.write_text(render(merge(template, entries, plural_count(header)), header), encoding="utf-8")
    print(f"{len(template)} strings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
