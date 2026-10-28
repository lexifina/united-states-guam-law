"""Print a chapter of the Guam Code Annotated, or one section of it, as this repository has it on a date.

    python tools/in_force_on.py 2026-10-01 title-01/chapter-016            # the whole chapter, in its order
    python tools/in_force_on.py 2026-10-01 title-01/chapter-016 1607       # 1 GCA section 1607
    python tools/in_force_on.py 2026-10-01 "1 GCA 1607"                    # the same, by citation
    python tools/in_force_on.py 2026-10-01 "6 GCA Rule 401"                # a Guam Rule of Evidence (6 GCA, App. A)

Reads the `In-force:` trailer, which holds the day the Compiler of Laws stamped on the chapter's pages. The Compiler
keeps only the current text, so a date before that day has no version here. Standard library only.
"""
import re
import subprocess
import sys


def git(*args: str) -> str:
    return subprocess.run(['git', '-c', 'core.quotepath=false', *args], capture_output=True, text=True,
                          encoding='utf-8', check=True).stdout


def by_citation(cite: str) -> tuple[str, str] | None:
    """'1 GCA 1607', '1 GCA \u00a7 1607', '6 GCA Rule 401' -> (chapter folder, file id), found in main's tree."""
    m = re.fullmatch(r'\s*(\d+)\s*G\.?C\.?A\.?\s*(?:\u00a7+|[Ss]ec(?:tion|\.)?)?\s*(Rule\s+)?([0-9][0-9A-Za-z.]*)\s*', cite)
    if not m:
        return None
    want = ('rule-' if m.group(2) else '') + m.group(3).rstrip('.')
    for path in git('ls-tree', '-r', '--name-only', 'main', 'title-%02d/' % int(m.group(1))).splitlines():
        folder, _, name = path.rpartition('/')
        if name == want + '.md':
            return folder, want
    return None


def commit_on(day: str, path: str) -> tuple[str | None, str | None]:
    """The last commit on or before `day` that touched `path`, and the earliest date known for it."""
    fmt = '%H%x1f%(trailers:key=In-force,valueonly,separator=)'
    earliest = None
    for line in git('log', '--first-parent', f'--format={fmt}', 'main', '--', path).splitlines():
        h, d = (line.split('\x1f') + [''])[:2]
        d = d.strip()
        if not d:
            continue
        earliest = d
        if d <= day:
            return h, d
    return None, earliest


def main() -> None:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')  # section signs, dashes and quotes outside the console code page
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    day = sys.argv[1]
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
        sys.exit(f'{day}: give the date as YYYY-MM-DD')
    if 'GCA' in sys.argv[2].upper().replace('.', ''):
        found = by_citation(sys.argv[2])
        if not found:
            sys.exit(f'{sys.argv[2]}: no such section in this repository')
        law, unit = found
    else:
        law = sys.argv[2].strip('/')
        unit = sys.argv[3] if len(sys.argv) > 3 else None
    if unit and unit.endswith('.md'):
        unit = unit[:-3]
    path = f'{law}/{unit}.md' if unit else law
    h, earliest = commit_on(day, path)
    if not h:
        if earliest:
            sys.exit(f'{path}: no version on or before {day}; the record starts at {earliest}, the day the Compiler '
                     'of Laws stamped on the chapter it publishes (it keeps no earlier text)')
        sys.exit(f'{path}: not found')
    if unit:
        sys.stdout.write(git('show', f'{h}:{path}'))
        return
    names = [n for n in git('show', f'{h}:{law}/index.txt').splitlines() if n]
    for n in names:
        sys.stdout.write(git('show', f'{h}:{law}/{n}') + '\n')


if __name__ == '__main__':
    main()
