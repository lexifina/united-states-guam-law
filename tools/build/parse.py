"""Read every cached Guam Code Annotated PDF into paragraphs.

    python parse.py --workers 1 [--force]   -> .cache/parsed/<pdf name>.json   (sequential; default 1)

Per PDF: the running headers and footers are removed by CONTENT (a line repeated on at least half the pages, the
"<n> GCA <TITLE>" / "CH. <n> ..." header patterns, bare page numbers, and the Compiler's "COL<m>/<d>/<yyyy>" stamp,
whose dates are kept as `stamps`). Lines on one baseline are merged; a paragraph starts after a vertical gap or a
deeper first-line indent. Each paragraph keeps whether it is entirely bold and its left edge.
"""
import json
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pymupdf

HERE = Path(__file__).parent
PDF = HERE / '.cache' / 'pdf'
OUT = HERE / '.cache' / 'parsed'

STAMP = re.compile(r'^\s*COL\s*[-:]?\s*([0-9][0-9./ -]{3,12}[0-9])\s*$')
STAMP_FORMS = [re.compile(r'^(?P<m>\d{1,2})[/.-](?P<d>\d{1,2})[/.-](?P<y>\d{4}|\d{2})$'),
               re.compile(r'^(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})$'),
               re.compile(r'^(?P<y>(?:19|20)\d{2})(?P<m>\d{2})(?P<d>\d{2})$'),
               re.compile(r'^(?P<m>\d{2})(?P<d>\d{2})(?P<y>\d{4})$'),
               re.compile(r'^(?P<m>\d)(?P<d>\d{2})(?P<y>\d{4})$'),
               re.compile(r'^(?P<m>\d{2})(?P<d>\d)(?P<y>\d{4})$'),
               re.compile(r'^(?P<m>\d{2})(?P<d>\d{2})(?P<y>\d{2})$'),
               re.compile(r'^(?P<m>\d)(?P<d>\d{2})(?P<y>\d{2})$'),
               re.compile(r'^(?P<m>\d)(?P<d>\d)(?P<y>\d{4})$')]


def stamp_readings(raw):
    """Every real date (1990-2030) a page stamp can mean, sorted. The Compiler has written the stamp in several
    styles over the years: 6/5/2019, 2026-05-29, 08222024, 7222015 (m dd yyyy), 110609 (mm dd yy). A seven-digit
    stamp can be ambiguous: "1242015" is 1/24/2015 or 12/4/2015."""
    import datetime
    raw = raw.replace(' ', '')
    out = set()
    for f in STAMP_FORMS:
        m = f.match(raw)
        if m:
            y, mo, d = int(m['y']), int(m['m']), int(m['d'])
            if y < 100:
                y += 2000
            if 1990 <= y <= 2030:
                try:
                    out.add(datetime.date(y, mo, d).isoformat())
                except ValueError:
                    pass
    return sorted(out)


# A stamp is on or before the day the PDF was saved, give or take a day or two (time zones; a file saved the
# evening before the stamp's day). The readings of an ambiguous seven-digit stamp lie months apart.
SAVE_SLACK_DAYS = 3


def save_day(meta):
    """The PDF's own save date: its ModDate, else its CreationDate, as YYYY-MM-DD; None when it has neither."""
    for k in ('modDate', 'creationDate'):
        m = re.match(r'D:(\d{4})(\d\d)(\d\d)', (meta or {}).get(k) or '')
        if m:
            return '-'.join(m.groups()), k
    return None, None


def resolve_stamp(raw, saved):
    """(date, note) for one raw stamp. One reading: that one. Several: the ones consistent with the save date (not
    after it, give or take SAVE_SLACK_DAYS); one left -> that one; still several (or none, or no save date) ->
    the reading closest to the save date, noted as ambiguous. (None, None) when no reading is a real date."""
    import datetime
    rs = stamp_readings(raw)
    if not rs:
        return None, None
    if len(rs) == 1:
        return rs[0], None
    if not saved:
        return rs[-1], f'ambiguous stamp {raw!r}: {" or ".join(rs)}; no save date, latest reading used'
    sd = datetime.date.fromisoformat(saved)
    lim = (sd + datetime.timedelta(days=SAVE_SLACK_DAYS)).isoformat()
    ok = [r for r in rs if r <= lim]
    if len(ok) == 1:
        return ok[0], None
    pool = ok or rs
    pick = min(pool, key=lambda r: (abs((datetime.date.fromisoformat(r) - sd).days), r))
    return pick, f'ambiguous stamp {raw!r}: {" or ".join(rs)}; saved {saved}, closest reading used'


def stamp_date(raw, saved=None):
    """The date one page stamp gives (see resolve_stamp); 'raw:<stamp>' when it gives none."""
    d, _ = resolve_stamp(raw, saved)
    return d or 'raw:' + raw.replace(' ', '')
HEADER = re.compile(r'^\s*\d+\s+G\.?\s?C\.?\s?A\.?\s*[A-Z][A-Z ,;&\'\u2019().-]*$|^\s*CH(?:APTER|\.)\s*\d+[A-Z]?\s+[A-Z\[(\u201c"]')
# The short running heads of the Rules of Evidence appendix ("ART. IV: RELEVANCY AND ITS LIMITS") and of divisions
# ("DIV. 2 PRINCIPLES OF EVIDENCE"): bold, small, in the first two lines of a page.
RUNNING = re.compile(r'^\s*(?:ART|DIV|SUBCH|SUBART)\.\s*[0-9IVXLC]+[A-Z]?\s*[:.]?\s+\S')
# The same heads in other spellings, accepted only bold and in the first two lines of a page: "TITLE 7 JUDICIARY AND
# CIVIL PROCEDURE", "20 REMEDIES" (no "GCA"), "Ch. 18 APPOINTMENT OF ADMINISTRATORS", "CH. 58A - Ma Kahat Act of
# 2008", "CH. 9.6 JUDICIAL CLIENT SERVICES FUND".
TOPHEAD = re.compile(r'^\s*(?:TITLE\s+)?\d+\s+[A-Z][A-Z ,;&\'\u2019().-]*$'
                     r'|^\s*(?i:CH)\.?\s*\d+(?:\.\d+)?[A-Z]?\s*[-\u2013\u2014]?\s+\S')
ENUM = re.compile(r'^\s*(?:\(\s*[0-9]{1,3}[A-Za-z]?\s*\)|\([a-z]{1,2}\)|\([ivxl]{1,6}\)|[0-9]{1,3}\.)\s+\S')
LIST_END = re.compile(r'(?:[.;:)]|\b(?:or|and))\s*$')
PAGENO = re.compile(r'^\s*(?:\d{1,4}|[ivxlc]{1,6}|-\s*\d+\s*-)\s*$', re.I)
WS = re.compile(r'[ \t\u00a0\u2002\u2003\u2009]+')
BULLET = re.compile(r'^\s*[\u2022\u25cf\u25aa\u00b7\uf0b7\uf0a7o\u2013-]\s*$')
SOFT = re.compile('[\u00ad\u200b\ufeff]')


def norm(s):
    return WS.sub(' ', SOFT.sub('', s)).strip()


def page_lines(page):
    """Lines of one page as dicts, merged per baseline, top to bottom."""
    raw = []
    for b in page.get_text('dict', flags=pymupdf.TEXT_PRESERVE_WHITESPACE)['blocks']:
        for l in b.get('lines', []):
            spans = [s for s in l['spans'] if s['text']]
            if not spans:
                continue
            raw.append({'x0': l['bbox'][0], 'y0': l['bbox'][1], 'y1': l['bbox'][3], 'spans': spans})
    raw.sort(key=lambda r: (round((r['y0'] + r['y1']) / 2), r['x0']))
    merged = []
    for r in raw:
        mid = (r['y0'] + r['y1']) / 2
        own = norm(''.join(sp['text'] for sp in r['spans']))
        only_bullet = BULLET.match(own) is not None
        # A running head or page stamp printed on the same baseline as a line of text stays a line of its own, so
        # it can be recognised and dropped (9 GCA Ch. 89 prints "CH. 89 ..." beside body lines).
        solo = max([sp['size'] for sp in r['spans'] if sp['text'].strip()] or [0]) < 10.5 and bool(HEADER.match(own) or STAMP.match(own))
        if (merged and abs(mid - merged[-1]['mid']) < 2.5 and not only_bullet and not merged[-1].get('bullet')
                and not solo and not merged[-1].get('solo')):
            m = merged[-1]
            m['parts'].append(r)
            m['y0'] = min(m['y0'], r['y0'])
            m['y1'] = max(m['y1'], r['y1'])
            continue
        merged.append({'mid': mid, 'y0': r['y0'], 'y1': r['y1'], 'parts': [r], 'bullet': only_bullet, 'solo': solo})
    out = []
    for m in merged:
        m['parts'].sort(key=lambda r: r['x0'])
        text, bold_chars, chars, size = '', 0, 0, 0
        for r in m['parts']:
            for s in r['spans']:
                t = s['text']
                text += (' ' if text and not text.endswith(' ') and not t.startswith(' ') and s is r['spans'][0] else '') + t
                n = len(t.strip())
                chars += n
                if n:  # a blank span's size says nothing (a 10.9 pt space ends many 9 pt running heads)
                    size = max(size, s['size'])
                if 'Bold' in s['font'] or (s['flags'] & 16):
                    bold_chars += n
        t = norm(text)
        if not t:
            continue
        xs = [r['x0'] for r in m['parts'] if norm(''.join(s['text'] for s in r['spans']))]
        out.append({'bullet': m['bullet'], 'text': t, 'x0': round(min(xs), 1), 'y0': round(m['y0'], 1), 'y1': round(m['y1'], 1),
                    'bold': chars > 0 and bold_chars >= chars * 0.9, 'size': round(size, 1)})
    return out


def parse(path):
    doc = pymupdf.open(path)
    pages = [page_lines(p) for p in doc]
    counts = {}
    for pl in pages:
        for t in {l['text'] for l in pl}:
            counts[t] = counts.get(t, 0) + 1
    many = len(pages) >= 3
    raws, dropped = set(), {}
    kept_pages = []
    for pl in pages:
        kept = []
        head = None  # the running-head line just dropped at the top of this page
        for i, l in enumerate(pl):
            t = l['text']
            m = STAMP.match(t)
            if m:
                raws.add(m.group(1).replace(' ', ''))
                dropped['stamp'] = dropped.get('stamp', 0) + 1
                continue
            if PAGENO.match(t):
                dropped['page-number'] = dropped.get('page-number', 0) + 1
                continue
            if (HEADER.match(t) or i < 2 and l['bold'] and (RUNNING.match(t) or TOPHEAD.match(t))) and l['size'] < 10.5:
                dropped['header'] = dropped.get('header', 0) + 1
                head = l if i < 3 else None
                continue
            # a running head that wraps: "CH. 21 COMMISSION ON DECOLONIZATION FOR THE" / "IMPLEMENTATION AND EXERCISE
            # OF CHAMORRO" / "SELF DETERMINATION" -- the next lines in the same small bold capitals, set tight under it
            if (head is not None and l['bold'] == head['bold'] and abs(l['size'] - head['size']) < 0.6
                    and l['size'] < 10.5 and l['y0'] - head['y1'] < 4 and t == t.upper() and any(c.isalpha() for c in t)):
                dropped['header-continued'] = dropped.get('header-continued', 0) + 1
                head = l
                continue
            head = None
            # a repeated running-head line is in capitals; a repeated sentence is text (two sections of 11 GCA Ch. 50
            # end with the same SOURCE note, near the top of a page)
            if (many and counts[t] >= len(pages) * 0.5 and l['size'] < 10.5 and (i < 3 or i >= len(pl) - 3)
                    and t == t.upper()):
                dropped['repeated'] = dropped.get('repeated', 0) + 1
                continue
            kept.append(l)
        kept_pages.append(kept)
    paras = []
    cur = None
    prev = None
    for pno, pl in enumerate(kept_pages):
        for k, l in enumerate(pl):
            new = cur is None or (prev is not None and prev.get('bullet'))
            if l.get('bullet'):
                new = True
            elif new and prev is not None and prev.get('bullet') and cur is not None and len(cur['lines']) == 1:
                new = False  # the text after a bullet glyph joins it
            if not new and cur is not None and not (prev is not None and prev.get('bullet')):
                if k == 0:  # first line of a page: continue unless indented deeper than the last line
                    new = l['x0'] > prev['x0'] + 6 or l['bold'] != prev['bold'] and l['text'].startswith('\u00a7')
                    # or the next item of a list: "(2) ... Guam, or" at the foot of one page, "(3) is adjudged ..."
                    # at the top of the next (a wrapped running head used to keep these apart by accident)
                    new = new or bool(ENUM.match(l['text']) and ENUM.match(cur['lines'][0])
                                      and LIST_END.search(prev['text']))
                else:
                    gap = l['y0'] - prev['y1']
                    new = gap > max(3.6, 0.42 * (prev['y1'] - prev['y0'])) or l['x0'] > prev['x0'] + 6
            if new:
                if cur:
                    paras.append(cur)
                cur = {'lines': [l['text']], 'bold': l['bold'], 'x0': l['x0'], 'page': pno + 1, 'size': l['size']}
            else:
                cur['lines'].append(l['text'])
                cur['bold'] = cur['bold'] and l['bold']
            prev = l
    if cur:
        paras.append(cur)
    out = []
    for p in paras:
        text = ''
        for ln in p['lines']:
            if not text:
                text = ln
            elif text.endswith('-') and not text.endswith(' -') and ln[:1].isalpha():
                text += ln
            else:
                text += ' ' + ln
        out.append({'text': norm(text), 'bold': p['bold'], 'x0': p['x0'], 'page': p['page'], 'size': p['size']})
    meta = {k: doc.metadata.get(k) for k in ('title', 'subject', 'creationDate', 'modDate')}
    saved, saved_from = save_day(meta)
    stamps, notes = set(), []
    for raw in sorted(raws):
        d, note = resolve_stamp(raw, saved)
        stamps.add(d or 'raw:' + raw)
        if note:
            notes.append(note)
    return {'pages': len(pages), 'stamps': sorted(stamps), 'stamp_raw': sorted(raws), 'stamp_notes': notes,
            'saved': saved, 'saved_from': saved_from, 'dropped': dropped, 'paras': out, 'meta': meta}


def one(name):
    dst = OUT / (name + '.json')
    src = PDF / name
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime and '--force' not in sys.argv:
        return name, None
    try:
        r = parse(src)
    except Exception as e:  # noqa
        return name, repr(e)
    tmp = dst.with_suffix('.tmp')
    tmp.write_text(json.dumps(r, ensure_ascii=False, sort_keys=True), encoding='utf-8', newline='\n')
    os.replace(tmp, dst)
    return name, None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    workers = int(sys.argv[sys.argv.index('--workers') + 1]) if '--workers' in sys.argv else 1
    only = [a for a in sys.argv[1:] if a.endswith('.pdf')]
    names = only or sorted(os.listdir(PDF))
    errs = []
    if workers <= 1:  # sequential: the process pool died twice on the build machine
        results = map(one, names)
    else:
        ex = ProcessPoolExecutor(workers)
        results = ex.map(one, names, chunksize=4)
    for i, (n, e) in enumerate(results):
        if e:
            errs.append((n, e))
        if i % 100 == 0:
            print(i, len(names), flush=True)
    print('done', len(names), 'errors', len(errs))
    for n, e in errs:
        print(' ', n, e)


if __name__ == '__main__':
    main()
