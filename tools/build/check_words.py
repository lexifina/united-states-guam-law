"""Independent letters-and-digits check: each chapter PDF against what git holds for it.

    python check_words.py C:/Users/alany/Documents/united-states-guam-law-build

The source side reads each PDF with PyMuPDF's plain `page.get_text()` and nothing from parse.py or build.py. It
removes, by its own simple rules, only what the build leaves out by design: the Compiler's page stamp ("COL6/5/2019"),
bare page numbers, and the running heads at the top of each page ("1 GCA GENERAL PROVISIONS", "CH. 16 COMPILER OF
LAWS", "ART. IV: RELEVANCY AND ITS LIMITS" in the first or last three lines of a page, or anywhere when written all
in capitals, or a line in capitals printed on at least half the pages: in the first or last three lines, or anywhere
if it has no digit or section sign). Text that repeats in lower case is never treated as a head.
The git side is every file of that chapter at main except index.txt. Both are reduced to a multiset of letters and
digits (casefolded), so order and markup ("## ") do not matter.

"missing" = in the PDF, not in git (dropped text). "extra" = in git, not in the PDF (text the build invented or
duplicated); extra letters held only in chapter.md are reported but not flagged. A chapter is flagged when its
section files hold more than 0.1% extra, or when more than 1% is missing.
"""
import csv
import io
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pymupdf

PDF = Path(__file__).resolve().parent / '.cache' / 'pdf'
STAMP = re.compile(r'^\s*COL\s*[-:]?\s*[0-9][0-9./ -]{3,12}[0-9]\s*$')
PAGENO = re.compile(r'^\s*(\d{1,4}|[ivxlc]{1,6}|-\s*\d+\s*-)\s*$', re.I)
HEAD = re.compile(r'^\s*(\d+\s+G\.?\s?C\.?\s?A\.?\s?[A-Z]|CH\.\s*\d|(ART|DIV|SUBCH|SUBART)\.\s*[0-9IVXLC]+)')


def letters(s: str) -> Counter:
    return Counter(c for c in s.casefold() if c.isalnum())


def source(pdf: Path) -> Counter:
    pages = [[l for l in p.get_text().splitlines() if l.strip()] for p in pymupdf.open(pdf)]
    tops = Counter(l.strip() for p in pages for l in set(p))  # on how many pages each line is printed
    out = Counter()
    for p in pages:
        for i, line in enumerate(p):
            edge = i < 3 or i >= len(p) - 3
            if STAMP.match(line) or edge and PAGENO.match(line):
                continue  # a bare number elsewhere is a table cell (5 GCA Ch. 1A's priority numbers)
            if HEAD.match(line) and (edge or line == line.upper()):
                continue  # a running head; get_text does not always put it first, so an all-capitals one anywhere
            caps = line == line.upper() and re.search('[A-Z]', line) and not re.search('[0-9\u00a7]', line)
            if len(pages) >= 3 and tops[line.strip()] >= len(pages) * 0.5 and (edge and line == line.upper() or caps):
                continue  # a repeated head line (the second line of a two-line running head, too)
            out += letters(line)
    return out


def main() -> None:
    repo = Path(sys.argv[1])

    def git(*a: str) -> str:
        return subprocess.run(['git', '-c', 'core.quotepath=false', '-C', str(repo), *a], capture_output=True,
                              text=True, encoding='utf-8', check=True).stdout

    tree: dict[str, list[str]] = {}
    for p in git('ls-tree', '-r', '--name-only', 'main').splitlines():
        if p.startswith('title-') and not p.endswith('/index.txt'):
            tree.setdefault(p.rsplit('/', 1)[0], []).append(p)
    cat = subprocess.Popen(['git', '-C', str(repo), 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def blob(spec: str) -> str:
        cat.stdin.write(spec.encode('utf-8') + b'\n')
        cat.stdin.flush()
        header = cat.stdout.readline().split()
        data = cat.stdout.read(int(header[2]))
        cat.stdout.read(1)
        return data.decode('utf-8')

    rows = list(csv.DictReader(io.StringIO(git('show', 'main:data/units.csv'))))
    results = []
    tot = miss_t = extra_t = 0
    for row in rows:
        d = row['path'].rstrip('/')
        g, front = Counter(), Counter()
        for p in tree.get(d, []):
            c = letters(blob(f'main:{p}'))
            g += c
            if p.endswith('/chapter.md'):
                front += c
        s = source(PDF / row['pdf'])
        miss, extra, total = sum((s - g).values()), sum((g - s).values()), sum(s.values()) or 1
        # extra letters a section file needs beyond the PDF: the front matter (chapter.md) can hold a running head
        # the check drops as such (the second line of a two-line head on page 1), which is still PDF text
        body_extra = sum(((g - front) - s).values())
        tot, miss_t, extra_t = tot + total, miss_t + miss, extra_t + extra
        results.append((body_extra / total, miss / total, d, miss, extra, total, ''.join((s - g).elements())[:40],
                        ''.join((g - s).elements())[:40], body_extra))
    cat.stdin.close()
    bad = [r for r in results if r[0] > 0.001 or r[1] > 0.01]
    print(f'checked {len(results)} chapters, {tot} source letters and digits: {miss_t} missing '
          f'({100 * miss_t / max(1, tot):.4f}%), {extra_t} extra ({100 * extra_t / max(1, tot):.4f}%), of which '
          f'{sum(r[8] for r in results)} outside chapter.md; '
          f'{len(bad)} chapters flagged; {sum(1 for r in results if not r[3] and not r[4])} exact')
    for r in sorted(bad, reverse=True)[:40]:
        print(f'  {r[2]}: missing {r[3]}/{r[5]} ({100 * r[1]:.2f}%) {r[6]!r}, extra {r[4]} ({100 * r[0]:.3f}%) {r[7]!r}')
    worst = sorted(results, key=lambda r: -(r[3] + r[4]))[:10]
    print('largest differences:', ', '.join(f'{r[2]} -{r[3]}/+{r[4]}' for r in worst))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
