#!/usr/bin/env python3
"""Refresh the area-skill indexes and CATALOG.md from the trap files.

Each area skill, skills/<area>/SKILL.md, is the source of truth for which traps it holds and
under which heading. To add a trap, drop its file into skills/<area>/references/ and add a line
`- [`name`](references/name.md)` under the right heading, then run this script. It:

  - rewrites every index line with the trap file's current description,
  - fails if a file under references/ is unlisted, listed twice, or listed but missing,
  - fails if a backticked cross-reference names a trap that no longer exists,
  - regenerates CATALOG.md,
  - reports how much of Claude Code's skill-listing budget the area skills take.

    python3 scripts/build_index.py          # rewrite in place
    python3 scripts/build_index.py --check  # change nothing; exit 1 if stale or invalid
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")
CATALOG = os.path.join(ROOT, "CATALOG.md")

# Claude Code lists every model-invocable skill as "- name: description" on every turn, within a
# budget of 1% of the context window at 4 characters per token — 8,000 characters for a
# 200K-token window. Past it, the least-used skills are listed by name only.
LISTING_BUDGET_200K = 8000
DESCRIPTION_CAP = 1536

ENTRY = re.compile(r"^- \[`([a-z0-9-]+)`\]\(references/([a-z0-9-]+)\.md\)(?: — .*)?$")
BACKTICKED = re.compile(r"`([a-z0-9]+(?:-[a-z0-9]+){2,})`")
# Backticked kebab-case tokens in the corpus that are identifiers, not references to a trap.
NOT_TRAP_NAMES = {"1970-01-01", "ui-graphics-android", "update-desktop-database"}


def frontmatter(path):
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    if lines[0] != "---":
        sys.exit(f"{path}: no frontmatter")
    end = lines.index("---", 1)
    fields = {}
    for line in lines[1:end]:
        key, _, value = line.partition(": ")
        fields[key] = unquote(value)
        fields["_raw_" + key] = value
    return fields, lines, end


def unquote(value):
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def yaml_unsafe(raw):
    # Strict YAML parsers (the skills CLI among them) reject a plain scalar containing ": " or
    # " #", or starting with an indicator character; Claude Code is lenient and hides the problem.
    if raw[:1] in "\"'":
        return False
    return ": " in raw or " #" in raw or raw[:1] in "[]{},&*!|>%@`-?:"


def main(check):
    errors = []
    areas = []
    traps = {}  # trap name -> area name

    for area in sorted(os.listdir(SKILLS)):
        skill_md = os.path.join(SKILLS, area, "SKILL.md")
        if not os.path.isfile(skill_md):
            continue
        fields, lines, end = frontmatter(skill_md)
        if fields.get("name") != area:
            errors.append(f"{area}: frontmatter name is {fields.get('name')!r}")
        if yaml_unsafe(fields.get("_raw_description", "")):
            errors.append(f"{area}: quote the description; strict YAML parsers reject it as written")
        ref_dir = os.path.join(SKILLS, area, "references")
        on_disk = {f[:-3] for f in os.listdir(ref_dir) if f.endswith(".md")} if os.path.isdir(ref_dir) else set()

        title, sections, listed, out = None, [], [], []
        for line in lines:
            if line.startswith("# ") and title is None:
                title = line[2:].strip()
            if line.startswith("## "):
                sections.append((line[3:].strip(), []))
            m = ENTRY.match(line)
            if m:
                name, target = m.groups()
                if name != target:
                    errors.append(f"{area}: entry `{name}` links to references/{target}.md")
                listed.append(name)
                if sections:
                    sections[-1][1].append(name)
                path = os.path.join(ref_dir, f"{name}.md")
                if os.path.isfile(path):
                    desc = frontmatter(path)[0].get("description", "")
                    line = f"- [`{name}`](references/{name}.md) — {desc}"
                else:
                    errors.append(f"{area}: `{name}` is listed but references/{name}.md does not exist")
            out.append(line)

        for name in sorted(on_disk - set(listed)):
            errors.append(f"{area}: references/{name}.md is not listed in SKILL.md")
        for name in sorted({n for n in listed if listed.count(n) > 1}):
            errors.append(f"{area}: `{name}` is listed more than once")
        for name in listed:
            if name in traps and traps[name] != area:
                errors.append(f"`{name}` is listed in both {traps[name]} and {area}")
            traps[name] = area

        new_text = "\n".join(out)
        with open(skill_md, encoding="utf-8") as f:
            old_text = f.read()
        if new_text != old_text:
            if check:
                errors.append(f"{area}/SKILL.md is stale: run scripts/build_index.py")
            else:
                with open(skill_md, "w", encoding="utf-8") as f:
                    f.write(new_text)

        areas.append(dict(name=area, title=title, description=fields.get("description", ""),
                          sections=sections, count=len(listed)))

    # Cross-references: a backticked kebab-case name that matches no trap is either an identifier
    # or a dangling reference to a trap that was renamed or removed.
    for area in areas:
        ref_dir = os.path.join(SKILLS, area["name"], "references")
        for f in sorted(os.listdir(ref_dir)) if os.path.isdir(ref_dir) else []:
            with open(os.path.join(ref_dir, f), encoding="utf-8") as fh:
                text = fh.read()
            for token in sorted(set(BACKTICKED.findall(text))):
                if token not in traps and token not in NOT_TRAP_NAMES:
                    errors.append(f"{area['name']}/references/{f}: `{token}` names no trap")

    catalog = render_catalog(areas)
    old_catalog = ""
    if os.path.exists(CATALOG):
        with open(CATALOG, encoding="utf-8") as fh:
            old_catalog = fh.read()
    if catalog != old_catalog:
        if check:
            errors.append("CATALOG.md is stale: run scripts/build_index.py")
        else:
            with open(CATALOG, "w", encoding="utf-8") as fh:
                fh.write(catalog)

    listing = sum(len(a["name"]) + 4 + min(len(a["description"]), DESCRIPTION_CAP) for a in areas)
    listing += max(0, len(areas) - 1)
    print(f"{len(traps)} traps in {len(areas)} area skills")
    print(f"skill listing: {listing} characters, {100 * listing // LISTING_BUDGET_200K}% of the "
          f"{LISTING_BUDGET_200K}-character budget of a 200K-token context")
    for a in areas:
        if len(a["description"]) > DESCRIPTION_CAP:
            errors.append(f"{a['name']}: description is over {DESCRIPTION_CAP} characters and will be cut")

    for e in errors:
        print("error:", e, file=sys.stderr)
    return 1 if errors else 0


def covers(description):
    # "Traps in X: a, b, c. Use when ..." -> "a, b, c"
    head = description.split(". Use ", 1)[0]
    return head.split(": ", 1)[1] if ": " in head else head


def render_catalog(areas):
    total = sum(a["count"] for a in areas)
    out = [
        "# Catalog",
        "",
        f"{total} traps in {len(areas)} area skills. Each area skill is an index an agent loads when",
        "it works in that area; each trap is a standalone markdown file inside it, read on demand.",
        "",
        "Generated by `scripts/build_index.py` from the area skills: edit those, then re-run it.",
        "",
        "| Area skill | Traps | Covers |",
        "|---|---|---|",
    ]
    for a in areas:
        out.append(f"| [`{a['name']}`](skills/{a['name']}/SKILL.md) | {a['count']} | {covers(a['description'])} |")
    for a in areas:
        out += ["", f"## {a['title']}", "", f"[`{a['name']}`](skills/{a['name']}/SKILL.md) · {a['count']} traps"]
        for section, names in a["sections"]:
            out += ["", f"### {section}", ""]
            out += [f"- [`{n}`](skills/{a['name']}/references/{n}.md)" for n in names]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv[1:]))
