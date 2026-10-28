"""README, REPRODUCE.md, SOURCES.md, LICENSE, corpus.json, data/ and tools for the Guam law repository (called by
build.py as `docs.files(units, rows, updated, retrieved, today)`; returns [(path, bytes)])."""
import csv
import hashlib
import io
import json
import os
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
REPO_FILES = HERE / 'repo'
CACHE = HERE / '.cache'
# Published with the record: what a reader needs to rebuild from the retrieved files and to check the result. The
# retrieval script and its notes stay private (the user's rule of 2026-10-29), and publish_gate (gitlaw_common,
# private) checks every file before it is written.
BUILD_FILES = ('parse.py', 'build.py', 'docs.py', 'check_words.py', 'asciify.py')
sys.path.insert(0, str(HERE.parent / 'gitlaw_common'))
try:
    from publish_gate import publish_gate  # noqa: E402
except ImportError:          # an outside reader rebuilding from the published tools: no private rule to apply
    if os.environ.get('GITLAW_PUBLIC_REBUILD') != '1':
        raise SystemExit('publish gate missing: run from lexifina/scripts, or set GITLAW_PUBLIC_REBUILD=1')

    def publish_gate(files): return files
TEMPLATES = ('README.md', 'REPRODUCE.md', 'SOURCES.md', 'LICENSE')

# A section of the Code is cited as "<title> GCA \u00a7 <number>"; the number is unique within its title, so the folder
# is the title. Inside a chapter's own text a bare "\u00a7 <number>" (or "Section <number>") is a citation of it.
CITATION = {
    'file': r'(title-[0-9]+)/[^/]+/((?:rule-)?[0-9][0-9A-Za-z.]*)\.md',
    # whole-character alternatives only: git grep may run in a byte locale, where "\u00a7?" would make only the
    # last byte of the section sign optional
    'cites': '(\u00a7\u00a7 ?|\u00a7 ?|[Ss]ection ){n}([^0-9A-Za-z.]|[.]([^0-9]|$)|$)',
    'note': 'files are <title folder>/<chapter folder>/<section>.md; section numbers are unique within a title '
            '(1 GCA \u00a7 1607 is title-01/chapter-016/1607.md). The Rules of Evidence are rule-<n>.md.',
}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _csv(rows: list[list]) -> bytes:
    out = io.StringIO()
    w = csv.writer(out, lineterminator='\n')
    for r in rows:
        w.writerow(r)
    return out.getvalue().encode('utf-8')


def source_sums() -> str:
    """sha256 of the index page and every chapter PDF the build read, so a rebuild can show it used the same input."""
    paths = [CACHE / 'index.html'] + sorted((CACHE / 'pdf').glob('*.pdf'))
    return ''.join(f'{p.relative_to(CACHE).as_posix()}\t{_sha(p)}\n' for p in paths)


def _pl_key(pl: str) -> tuple:
    return tuple(int(v) for v in pl[5:].split('-'))


def files(units: list[dict], rows: list[list], updated: str | None, retrieved: str, today: str) -> list[tuple]:
    days = sorted(u['date'] for u in units)
    by_year = Counter(d[:4] for d in days)
    laws = sorted({r[3] for r in rows}, key=_pl_key)
    sections = sum(len(u['sections']) for u in units)
    stats = {
        'today': today, 'retrieved': retrieved, 'updated_through': updated or '',
        'units': len(units), 'titles': len({u['title'] for u in units}), 'sections': sections,
        'files': sections + sum(1 for u in units if u['front']),
        'no_sections': sum(1 for u in units if not u['sections']),
        'commits': len(units) + 1, 'consolidated': len(units), 'amendment': 0, 'unexplained': 0,
        'first': days[0], 'last': days[-1],
        'page_stamped': sum(1 for u in units if u['date_source'] == 'page-stamp'),
        'retrieved_dated': sum(1 for u in units if u['date_source'] == 'retrieved'),
        'ambiguous_stamps': sum(1 for u in units if u.get('date_note') == 'ambiguous stamp'),
        'pages': sum(u['pages'] for u in units),
        'citations': len(rows), 'public_laws': len(laws), 'dated_citations': sum(1 for r in rows if r[5]),
        'latest_cited': laws[-1] if laws else '',
        'compiled_by_year': dict(sorted(by_year.items())),
    }

    def fill(text: str) -> str:
        for k, v in stats.items():
            if isinstance(v, (str, int)):
                text = text.replace('{{' + k.upper() + '}}', f'{v:,}' if isinstance(v, int) else v)
        for name in BUILD_FILES:
            text = text.replace('{{SHA_' + name.upper().replace('.', '_') + '}}', _sha(HERE / name))
        if '{{' in text:
            raise SystemExit('unfilled placeholder: ' + text[text.index('{{'):text.index('{{') + 40])
        return text

    units_csv = _csv([['path', 'title', 'title_name', 'division', 'label', 'compiled', 'date_source', 'date_note',
                       'pages', 'sections', 'citations', 'pdf', 'source_url']] +
                     [[u['dir'] + '/', u['title'], u['title_name'], u['division'] or '', u['label'], u['date'],
                       u['date_source'], u.get('date_note', ''), u['pages'], len(u['sections']),
                       sum(1 for r in rows if r[0].startswith(u['dir'] + '/')), u['file'], u['url']] for u in units])
    amend_csv = _csv([['file', 'section', 'citation', 'public_law', 'kind', 'date', 'note']] + rows)

    corpus = {
        'corpus': 'us/guam/acts',
        'parent': 'us/federal/usc',
        'name': 'Guam Code Annotated (the laws of Guam, as compiled by the Office of the Compiler of Laws)',
        'label': 'Guam',
        'language': 'en',
        'history': 'current-only',
        'history_from': days[0],
        'record_to': days[-1],
        'checked_on': retrieved,
        'record_note': 'The Compiler of Laws publishes only the current text of each chapter of the Guam Code '
                       'Annotated and keeps no earlier versions, so each chapter has one version here: the text as '
                       f'compiled on the day stamped on its pages. The index says "Updated through {updated}". '
                       'There is no line-by-line history before that. The SOURCE notes naming each public law are '
                       'kept as text and listed in data/amendments.csv.',
        'built': today,
        'baseline_trailer': 'Consolidated',
        'in_force_trailer': 'In-force',
        'dates': {'commit': "the date the Compiler stamped on the chapter's pages (\"COL 2026-05-29\"); the "
                            'retrieval day where a chapter has no stamp',
                  'baseline_trailer': 'Consolidated', 'other_trailers': ['Date-source', 'Date-note'],
                  'time': '12:00 UTC+10 (Chamorro Standard Time, no daylight saving time)'},
        'author': {'consolidated': 'Guam Compiler of Laws', 'amendment': 'none yet',
                   'unexplained': 'Guam Compiler of Laws'},
        'scope': {
            'trailer': 'Applies',
            'when_absent': 'not extracted for Guam; effective-date and savings provisions are in the public laws '
                           'and, where the Compiler kept them, in the NOTE lines under each section',
            'default_reach': {
                'rule': 'presumption against retroactivity',
                'meaning': 'no part of the Guam Code is retroactive unless expressly so declared',
                'authority': '1 GCA \u00a7 702 ("No part of this Code is retroactive, unless expressly so declared.")',
                'decided_here': False,
            },
        },
        'reuse': 'Statute text is not copyrightable: under the government edicts doctrine (Georgia v. '
                 'Public.Resource.Org, Inc., 590 U.S. 255 (2020)) nobody owns works made by legislators or judges '
                 'in their official capacity. 1 GCA \u00a7 1607 lets the government of Guam copyright the '
                 "Compiler's work product and keep the form and structure of the laws public. Private repository; "
                 'see SOURCES.md.',
        'citation': CITATION,
        'has_future_branch': False,
        'tool': 'tools/in_force_on.py',
    }

    out = {
        'corpus.json': (json.dumps(corpus, indent=2, ensure_ascii=False) + '\n').encode('utf-8'),
        'data/amendments.csv': amend_csv,
        'data/units.csv': units_csv,
        'data/stats.json': (json.dumps(stats, indent=1, sort_keys=True) + '\n').encode('utf-8'),
        'data/source-sha256.tsv': source_sums().encode('utf-8'),
        'tools/in_force_on.py': (REPO_FILES / 'tools' / 'in_force_on.py').read_bytes(),
    }
    for name in TEMPLATES:
        out[name] = fill((REPO_FILES / name).read_text('utf-8')).encode('utf-8')
    for name in BUILD_FILES:
        out[f'tools/build/{name}'] = (HERE / name).read_bytes()
    for name in TEMPLATES:
        out[f'tools/build/repo/{name}'] = (REPO_FILES / name).read_bytes()
    out['tools/build/repo/tools/in_force_on.py'] = (REPO_FILES / 'tools' / 'in_force_on.py').read_bytes()
    out = publish_gate(out)
    for k, v in out.items():
        if b'\r' in v:
            raise SystemExit(f'{k}: carriage return in a generated file')
    return sorted(out.items())
