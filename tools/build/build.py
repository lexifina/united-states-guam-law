"""Build the Guam law repository from the Compiler of Laws cache (fetch.py, then parse.py).

    python build.py C:/Users/alany/Documents/united-states-guam-law --today 2026-10-28 [--stats]

The Office of the Compiler of Laws publishes only the current text of each chapter of the Guam Code Annotated, one
PDF per chapter, and keeps no past versions. So this record is current-only (the Fiji and Turkey pattern):

1. Every chapter PDF (Title 13: every Division; Title 20: Part 4; plus the chapter attachments, exhibits and the
   probate forms) is one unit. Its front matter (chapter heading, chapter SOURCE note, section list) is
   `chapter.md`; each section, from its bold "\u00a7 N. Heading." line to the next, is `<N>.md`, one paragraph per line.
   Article and subchapter headings go on top of the next section file as `##` lines.
2. Each unit is one commit, `Kind: consolidated`, authored by the Compiler of Laws, dated noon Guam time (UTC+10,
   no daylight saving) on the date the Compiler stamped on the PDF's pages ("COL 2026-05-29"). The text is the
   chapter as compiled on that day; the SOURCE notes name the public laws behind each section and are listed in
   data/amendments.csv. No line is credited to a public law, because the text before each amendment is not
   published.
3. A documentation commit (README, REPRODUCE.md, corpus.json, tools, data) closes the history, dated by the
   retrieval day. The same cache always gives the same hashes (one git fast-import, messages as bytes).
"""
import argparse
import csv
import hashlib
import html
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / '.cache'
PARSED = CACHE / 'parsed'
SITE = 'https://col.guamcourts.gov'
INDEX_URL = SITE + '/guam-code-annotated/guam-code-annotated'
SLUG = 'united-states-guam-law'
COMMITTER = ('Lexifina', SLUG + '@lexifina.com')
PUBLISHER = ('Guam Compiler of Laws', 'compiler-of-laws@guamcourts.invalid')
TZ = '+1000'  # Chamorro Standard Time, UTC+10 all year: Guam has observed no daylight saving time since 1977

SKIP_LABELS = re.compile(r'^(Table of Contents|Introduction|Estates & Probate Subject Index|.*Organic Act of Guam'
                         r'|Purchase the Guam Code)', re.I)
SECTION = re.compile(r'^\u00a7\u00a7?\s*([0-9][0-9A-Za-z.]*(?:\s*(?:[-\u2013\u2014]|to|and|&|,)\s*[0-9][0-9A-Za-z.]*)*)'
                     r'\s*[.:]?(?:\s|$)')
PL = re.compile(r'(?<![A-Za-z.])P\.\s?L\.\s*(\d{1,2})\s*-\s*(\d{1,3})((?::[0-9A-Za-z]+(?:\([0-9A-Za-z]+\))*)*)\s*'
                r'(?:\(([A-Z][a-z]{2,9}\.?\s*\d{1,2},?\s*\d{4}|\d{1,2}/\d{1,2}/\d{2,4})\))?')
VERB = re.compile(r'(repealed\s*(?:/|and)\s*re-?enacted|R/R|re-?enacted|added|amended|repealed|renumbered|recodified|'
                  r'codified|enacted|deleted|substituted|redesignated|adopted|reorganized|moved)', re.I)
MONTHS = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov',
                                      'dec'], 1)}


# ---------------------------------------------------------------------------------------------- manifest

def manifest():
    """Every chapter PDF in the order of the Compiler's index page, with its title, division/part and label."""
    s = (CACHE / 'index.html').read_text('utf-8', errors='replace')
    s = s[s.find('OrganicAct2025Note'):]
    s = re.sub(r'<script.*?</script>|<style.*?</style>', '', s, flags=re.S)
    toks = re.findall(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>|<li[^>]*>([^<]{3,300})', s, flags=re.S)
    title = None
    division = None
    out = []
    updated = re.search(r'Updated through (P\.L\. [0-9-]+ \([^)]+\))', (CACHE / 'index.html').read_text('utf-8', errors='replace'))
    for href, label, text in toks:
        if href:
            label = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', label))).strip()
            m = re.match(r'#faq(\d+)$', href)
            if m:
                tm = re.match(r'Title (\d+):\s*(.*)', label)
                title = (int(tm.group(1)), tm.group(2).strip())
                division = None
                continue
            if not href.startswith('/sites/default/files/') or not href.lower().endswith('.pdf') or title is None:
                continue
            if SKIP_LABELS.match(label):
                continue
            fname = href.rsplit('/', 1)[1].replace('%20', ' ')
            out.append({'title': title[0], 'title_name': title[1], 'division': division, 'label': label,
                        'file': fname, 'url': SITE + href})
        else:
            t = re.sub(r'\s+', ' ', html.unescape(text)).strip()
            if re.match(r'(Division|Part) ', t):
                division = t
    return out, (updated.group(1) if updated else None)


def unit_dir(u, taken):
    """title-05/chapter-022, title-13/division-01, title-20/part-4, title-15/chapter-033-attachment-a ..."""
    t = 'title-%02d' % u['title']
    label = u['label']
    m = re.match(r'(Chapter|Division|Part)s?\s*([0-9]+(?:\.[0-9]+)?[A-Za-z]?)\b', label)
    if m:
        kind, num = m.group(1).lower(), m.group(2)
        n = re.match(r'(\d+)(.*)', num)
        name = '%s-%03d%s' % (kind, int(n.group(1)), n.group(2).upper()) if kind == 'chapter' else '%s-%02d%s' % (
            kind, int(n.group(1)), n.group(2).upper())
    else:
        base = re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-')[:50]
        fm = re.match(r'\d+gc(\d+)', u['file'].lower())
        name = ('chapter-%03d-' % int(fm.group(1)) if fm and 'attachment' in base or fm and 'exhibit' in base
                else '') + base
    d = f'{t}/{name}'
    k = 2
    while d in taken:
        d = f'{t}/{name}-{k}'
        k += 1
    taken.add(d)
    return d


# ---------------------------------------------------------------------------------------------- sections

def section_id(text):
    m = SECTION.match(text)
    if not m:
        return None
    sid = re.sub(r'\s+', '', m.group(1)).rstrip('.')
    sid = sid.replace('\u2013', '-').replace('\u2014', '-').replace('to', '-').replace('and', '-').replace('&', '-')
    sid = re.sub(r'[^0-9A-Za-z.,-]', '', sid).replace(',', '-')
    return sid or None


RULE = re.compile(r'^Rule\s+([0-9]+(?:\.[0-9]+)*[A-Z]?)\.(?:\s|$)')
FORM = re.compile(r'^OFFICIAL FORM NO\.\s*([0-9]+[A-Z]?)\s*$')
APPENDIX = re.compile(r'^APPENDIX ([A-Z])\b')


def start_id(p, loose):
    """The file id a paragraph opens, or None. A section opens at a bold "\u00a7 N." line; the 2006 Guam Rules of
    Evidence (6 GCA, Appendix A) at a bold "Rule N." line (`rule-N`); the probate forms (15 GCA, Appendix A) at an
    "OFFICIAL FORM NO. N" line (`form-N`). `loose`: the unit has no bold section line at all (6 GCA Division 1,
    whose three sections have no heading), so a plain paragraph that is one whole section ("\u00a7 101. The Supreme
    Court ...", one section sign, longer than a section-list entry) opens one too."""
    t = p['text']
    if p['bold']:
        sid = section_id(t)
        if sid:
            return sid
        m = RULE.match(t)
        if m:
            return 'rule-' + m.group(1)
        return None
    m = FORM.match(t)
    if m:
        return 'form-' + m.group(1)
    if loose and t.count('\u00a7') == 1 and len(t) > 80:
        return section_id(t)
    return None


def split_unit(paras):
    """-> (front lines, [(section id, lines)]). A section starts where `start_id` says; other bold paragraphs
    (Article/Subchapter headings) become `##` lines on top of the next section. A bold "APPENDIX A" heading after
    the sections opens its own file (`appendix-a`) for the appendix's title page and contents."""
    front, sections, pending = [], [], []
    cur = None
    loose = not any(p['bold'] and section_id(p['text']) for p in paras)
    for p in paras:
        t = p['text']
        sid = start_id(p, loose)
        if not sid and cur is not None and p['bold'] and APPENDIX.match(t):
            sid = 'appendix-' + APPENDIX.match(t).group(1).lower()
            t = '## ' + t
        if sid:
            cur = (sid, pending + [t])
            pending = []
            sections.append(cur)
            continue
        if cur is None:
            front.append(t)
            continue
        if p['bold'] and not t.startswith('\u00a7') and len(t) < 300 and not re.match(r'(SOURCE|COMMENT|NOTE|\d{4} NOTE)', t):
            pending.append('## ' + t)
            continue
        if pending:
            cur[1].extend(pending)
            pending = []
        cur[1].append(t)
    if pending:
        (sections[-1][1] if sections else front).extend(pending)
    return front, sections


def file_names(sections):
    used = {}
    out = []
    for sid, lines in sections:
        base = sid.replace('/', '-')
        n = used.get(base, 0) + 1
        used[base] = n
        out.append((base if n == 1 else f'{base}-{n}', sid, lines))
    return out


# ---------------------------------------------------------------------------------------------- notes

def pl_date(s):
    """'Dec. 6, 2012' or '12/30/94' -> '2012-12-06' / '1994-12-30'; '' when it is not a real date."""
    if not s:
        return ''
    m = re.match(r'([A-Z][a-z]{2})[a-z]*\.?\s*(\d{1,2}),?\s*(\d{4})$', s)
    if m:
        if m.group(1).lower() not in MONTHS:
            return ''
        y, mo, d = int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))
    else:
        m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$', s)
        if not m:
            return ''
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 1900 if y >= 50 else 2000
    if not (1 <= mo <= 12 and 1 <= d <= 31 and 1950 <= y <= 2100):
        return ''
    return '%04d-%02d-%02d' % (y, mo, d)


def note_rows(path, sid, lines):
    """One row per public law a SOURCE note cites: (file, section, citation, public law, kind, date, note). `kind`
    is the last verb before the citation in the note ("Amended by P.L. 22-158:3" -> amended), carried over a list
    ("Amended by P.L. 1-1, P.L. 2-2"); `cited` when the note names none. The date is the one printed beside the
    citation (the law's approval date), '' when none is printed."""
    rows = []
    for ln in lines:
        if not re.match(r'(SOURCE|Source)\s*:', ln):
            continue
        kind, pos = 'cited', 0
        for m in PL.finditer(ln):
            verbs = VERB.findall(ln[pos:m.start()])
            if verbs:
                v = verbs[-1].lower().replace(' ', '')
                kind = ('repealed and reenacted' if v.startswith('repealed') and 'enact' in v or v == 'r/r'
                        else v.replace('-', ''))
            pos = m.end()
            pl = 'P.L. %d-%03d' % (int(m.group(1)), int(m.group(2)))
            rows.append([path, sid, pl + (m.group(3) or ''), pl, kind, pl_date(m.group(4)), ln])
    return rows


# ---------------------------------------------------------------------------------------------- git

class Writer:
    def __init__(self, repo):
        self.p = subprocess.Popen(['git', 'fast-import', '--quiet', '--done', '--force'], cwd=repo,
                                  stdin=subprocess.PIPE)
        self.mark = 0

    def w(self, b):
        self.p.stdin.write(b)

    def data(self, b):
        self.w(b'data %d\n' % len(b) + b + b'\n')

    def commit(self, author, when, message, files, deleteall=False):
        self.mark += 1
        self.w(b'commit refs/heads/main\nmark :%d\n' % self.mark)
        self.w(('author %s <%s> %s\n' % (author[0], author[1], when)).encode('utf-8'))
        self.w(('committer %s <%s> %s\n' % (COMMITTER[0], COMMITTER[1], when)).encode('utf-8'))
        self.data(message.encode('utf-8'))
        if self.mark > 1:
            self.w(b'from :%d\n' % (self.mark - 1))
        for path, content in files:
            self.w(('M 100644 inline %s\n' % path).encode('utf-8'))
            self.data(content if isinstance(content, bytes) else content.encode('utf-8'))

    def done(self):
        self.w(b'done\n')
        self.p.stdin.close()
        if self.p.wait():
            raise SystemExit('fast-import failed')


def when(day):
    """Noon in Guam (UTC+10) on `day`, as a git date. Same-day commits share it; the parent chain orders them."""
    import calendar
    y, m, d = map(int, day.split('-'))
    return '%d %s' % (calendar.timegm((y, m, d, 2, 0, 0)), TZ)  # 12:00 UTC+10 = 02:00 UTC


# ---------------------------------------------------------------------------------------------- main

def load_units(today):
    units, updated = manifest()
    taken = set()
    log = json.loads((CACHE / 'fetch-log.json').read_text())
    for u in units:
        u['dir'] = unit_dir(u, taken)
        r = json.loads((PARSED / (u['file'] + '.json')).read_text('utf-8'))
        stamps = [s for s in r['stamps'] if s and not s.startswith('raw')]
        key = u['url'].split('/sites/default/files/')[1]
        u['retrieved'] = log.get(key, {}).get('fetched', today)
        if stamps:
            u['date'], u['date_source'] = max(stamps), 'page-stamp'
        else:
            u['date'], u['date_source'] = u['retrieved'], 'retrieved'
        u['pages'] = r['pages']
        front, sections = split_unit(r['paras'])
        u['front'] = front
        u['sections'] = file_names(sections)
    return units, updated


def unit_files(u):
    files = [(f"{u['dir']}/chapter.md", '\n'.join(u['front']) + '\n')] if u['front'] else []
    for name, sid, lines in u['sections']:
        files.append((f"{u['dir']}/{name}.md", '\n'.join(lines) + '\n'))
    # index.txt names the files in the chapter's order (file names alone sort 101 after 1001)
    files.append((f"{u['dir']}/index.txt", ''.join(p.rsplit('/', 1)[1] + '\n' for p, _ in files)))
    return files


def message(u, rows):
    pls = sorted({r[3] for r in rows}, key=lambda x: tuple(int(v) for v in x[5:].split('-')))
    last = pls[-1] if pls else None
    lab = u['label']
    subj = f"{u['title']} GCA {lab.split(':')[0].strip()}: as compiled {u['date']}"
    body = (f"The text of {u['title']} GCA ({u['title_name']}), {lab}, as the Office of the Compiler of Laws publishes "
            f"it, {'stamped' if u['date_source'] == 'page-stamp' else 'retrieved'} {u['date']}.\n"
            "The Compiler keeps no earlier versions, so this commit holds the whole text and no line is credited to\n"
            "a public law. The SOURCE notes under each section name the laws behind it; they are listed in\n"
            f"data/amendments.csv ({len(rows)} citations of {len(pls)} public laws).")
    tr = ['Kind: consolidated', f"Consolidated: {u['date']}", f"In-force: {u['date']}",
          f"Law: {u['title']} GCA {lab}", f"Date-source: {u['date_source']}", f"Sections: {len(u['sections'])}"]
    if last:
        tr.append(f'Latest-cited: {last}')
    tr.append(f"Source: {u['url']}")
    return subj + '\n\n' + body + '\n\n' + '\n'.join(tr) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('repo')
    ap.add_argument('--today', required=True)
    ap.add_argument('--stats', action='store_true')
    a = ap.parse_args()
    units, updated = load_units(a.today)
    rows_by = {}
    allrows = []
    for u in units:
        rows = []
        for name, sid, lines in u['sections']:
            rows += note_rows(f"{u['dir']}/{name}.md", sid, lines)
        rows_by[u['dir']] = rows
        allrows += rows
    if a.stats:
        ns = sum(len(u['sections']) for u in units)
        print(len(units), 'units', ns, 'sections', len(allrows), 'P.L. citations', updated)
        for u in units:
            if not u['sections']:
                print('  no sections:', u['dir'], u['file'], len(u['front']))
        return
    repo = Path(a.repo)
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / '.git').exists():
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=repo, check=True)
        subprocess.run(['git', 'config', 'core.autocrlf', 'false'], cwd=repo, check=True)
    elif subprocess.run(['git', 'rev-parse', '-q', '--verify', 'refs/heads/main'], cwd=repo,
                        capture_output=True).returncode == 0:
        raise SystemExit(f'{repo} already has a main branch: build into a new, empty folder')
    late = [u['dir'] for u in units if u['date'] > a.today]
    if late:
        raise SystemExit(f'{len(late)} units dated after --today {a.today}: {late[:5]}')
    order = sorted(units, key=lambda u: (u['date'], u['dir']))
    import docs
    retrieved = max(u['retrieved'] for u in units)
    w = Writer(repo)
    for u in order:
        w.commit(PUBLISHER, when(u['date']), message(u, rows_by[u['dir']]), unit_files(u))
    w.commit(COMMITTER, when(retrieved),
             f'Documentation: README, REPRODUCE, tools and data\n\nBuilt from the Compiler of Laws cache retrieved '
             f'{retrieved}.\n\nKind: documentation\nIn-force: {retrieved}\n',
             docs.files(units, allrows, updated, retrieved, a.today))
    w.done()
    subprocess.run(['git', 'checkout', '-q', '-f', 'main'], cwd=repo, check=True)
    print('built', len(order) + 1, 'commits')


if __name__ == '__main__':
    main()
