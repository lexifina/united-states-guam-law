"""Independent letters-and-digits check: each chapter PDF against what git holds for it.

    python check_words.py ~/Documents/united-states-guam-law-build

The source side reads each PDF with PyMuPDF's plain `page.get_text()` and nothing from parse.py or build.py. It
removes, by its own simple rules, only what the build leaves out by design: the Compiler's page stamp ("COL6/5/2019"),
bare page numbers, and the running heads at the top of each page ("1 GCA GENERAL PROVISIONS", "CH. 16 COMPILER OF
LAWS", "ART. IV: RELEVANCY AND ITS LIMITS" in the first or last three lines of a page, or anywhere when written all
in capitals, or a line in capitals printed on at least half the pages: in the first or last three lines, or anywhere
if it has no digit or section sign). At the top of a page, the stamp, page number and head lines in the first six
lines are one block, with the capital lines a head wraps onto and a "TITLE 7 JUDICIARY ..." / "20 REMEDIES" line
just above a head; the block ends at the first other line. Text that repeats in lower case is never treated as a head.
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
HEAD = re.compile(r'^\s*(\d+\s+G\.?\s*C\.?\s?A\.?\s*[A-Z]|[Cc][Hh]\.?\s*\d|(ART|DIV|SUBCH|SUBART)\.\s*[0-9IVXLC]+)')
# a running head's first line written without "GCA" ("TITLE 7 JUDICIARY AND CIVIL PROCEDURE", "20 REMEDIES")
TITLE_HEAD = re.compile(r'^\s*(TITLE\s+)?\d+\s+[A-Z][A-Z ,;&\'\u2019().-]*$')
# the first lines of the text itself, which a running head never starts with
BODY_HEAD = re.compile(r'^\s*(CHAPTER|ARTICLE|PART|SUBARTICLE|SUBCHAPTER|DIVISION|APPENDIX|TITLE\s+[0-9IVXL]+\s*$|\u00a7'
                       r'|SOURCE|CROSS-REFERENCE|COMMENT|NOTE|\[?\d{4}\]?\s+NOTE)')
NO_SIZE = (99.0, False, 0.0, 0.0)


def letters(s: str) -> Counter:
    return Counter(c for c in s.casefold() if c.isalnum())


def top_block(p: list[str], size: dict[str, tuple]) -> set[int]:
    """Indices of the running-head block at the top of a page: the stamp, page number and head lines in the first
    six lines, with the lines a head wraps onto ("CH. 21 COMMISSION ON DECOLONIZATION FOR THE" / "IMPLEMENTATION AND
    EXERCISE OF CHAMORRO" / "SELF DETERMINATION"): capitals, right under a head line, until the first line that is
    not one (the "CHAPTER 21" heading of the text, or any lower-case line). A wrapped line must be in the head's
    small bold type (under 10.5 pt, within 0.6 pt of a bold head line), set less than 4 pt below the line above it,
    and not a note ("SOURCE: GC 4111."); `size` gives each line's largest font size, whether it is all bold, and
    its top and bottom."""
    out, head = set(), None
    for i, line in enumerate(p[:6]):
        caps = line == line.upper() and re.search('[A-Z]', line)
        sz, bold, y0, y1 = size.get(line.strip(), NO_SIZE)
        if STAMP.match(line) or PAGENO.match(line):
            out.add(i)
        elif HEAD.match(line) or i < 2 and TITLE_HEAD.match(line) and i + 1 < len(p) and HEAD.match(p[i + 1]):
            out.add(i)
            head = (sz, bold, y1)
        elif (head is not None and head[1] and bold and caps and not BODY_HEAD.match(line)
              and sz < 10.5 and abs(sz - head[0]) < 0.6 and y0 - head[2] < 4):
            out.add(i)
            head = (head[0], head[1], y1)
        else:
            break
    return out


def sizes(page) -> dict[str, tuple]:
    """Each line's text -> (largest font size, all bold, top, bottom), ignoring blank spans, from PyMuPDF's dict
    output. A text printed twice on the page keeps its first place (the top of the page comes first)."""
    out: dict[str, tuple] = {}
    for b in page.get_text('dict')['blocks']:
        for l in b.get('lines', []):
            spans = [s for s in l['spans'] if s['text'].strip()]
            t = ''.join(s['text'] for s in l['spans']).strip()
            sz = max([s['size'] for s in spans] or [0.0])
            bold = bool(spans) and all('Bold' in s['font'] or s['flags'] & 16 for s in spans)
            if t not in out or l['bbox'][1] < out[t][2]:
                out[t] = (sz, bold, l['bbox'][1], l['bbox'][3])
    return out


def source(pdf: Path) -> Counter:
    doc = pymupdf.open(pdf)
    pages = [[l for l in p.get_text().splitlines() if l.strip()] for p in doc]
    page_sizes = [sizes(p) for p in doc]
    tops = Counter(l.strip() for p in pages for l in set(p))  # on how many pages each line is printed
    out = Counter()
    for p, size in zip(pages, page_sizes):
        block = top_block(p, size)
        for i, line in enumerate(p):
            edge = i < 3 or i >= len(p) - 3
            if i in block:
                continue
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
