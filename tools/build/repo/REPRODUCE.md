# Reproducing this repository

Built on {{TODAY}} from the Guam Code Annotated PDFs retrieved {{RETRIEVED}}, by the scripts in `tools/build/` (copied there as run). [`data/source-sha256.tsv`](data/source-sha256.tsv) lists the sha256 of the index page and of each PDF the build read, so a copy of those files can be checked byte for byte before rebuilding. How the files were retrieved is not part of this record.

| Script | sha256 |
| --- | --- |
| parse.py | `{{SHA_PARSE_PY}}` |
| build.py | `{{SHA_BUILD_PY}}` |
| docs.py | `{{SHA_DOCS_PY}}` |
| check_words.py | `{{SHA_CHECK_WORDS_PY}}` |
| asciify.py | `{{SHA_ASCIIFY_PY}}` |

Python 3.10 or later, PyMuPDF (`pip install pymupdf`) and git.

## Steps

With the retrieved index page and chapter PDFs in place (each matching its sha256 in `data/source-sha256.tsv`), and the day each was retrieved:

```sh
# 1. Read each PDF into paragraphs. Run it in one process: a pool of workers died twice on the build machine.
#    About 4 minutes.
python parse.py --workers 1
# 2. Build into a new, empty folder. --today dates the build and is the latest date allowed.
python build.py ../united-states-guam-law-build --today {{TODAY}}
```

With the same files, `build.py` gives the same commit hashes, because it writes the whole history in one `git fast-import` stream, sorted, with fixed dates and messages written as bytes.

## What the build produced

- {{UNITS}} chapters (and divisions, parts, appendices and attachments) from {{TITLES}} titles: {{PAGES}} pages.
- {{FILES}} text files: {{SECTIONS}} sections, rules and forms, plus a `chapter.md` per chapter for its front matter. {{NO_SECTIONS}} chapters print no section and are held whole in `chapter.md`.
- {{COMMITS}} commits: {{CONSOLIDATED}} consolidated (one per chapter) and one documentation commit.
- Compilation dates from {{FIRST}} to {{LAST}}: {{PAGE_STAMPED}} from the Compiler's page stamps, {{RETRIEVED_DATED}} from the retrieval day.
- {{CITATIONS}} public-law citations in the SOURCE notes, of {{PUBLIC_LAWS}} public laws (`data/amendments.csv`).

## Checks

```sh
python ../lexifina/scripts/global-law/check_corpus.py .     # the shared preflight
git rev-list --merges --count main                          # 0
git log --format='%(trailers:key=In-force,valueonly)' main | grep . | sort -c -r   # dates never go back
git log --format=%B main | grep -c $'\r'                    # 0
python tools/in_force_on.py {{TODAY}} "1 GCA 1607"
python tools/in_force_on.py {{TODAY}} "6 GCA Rule 401"
```

The letters-and-digits check (`check_words.py` in the build scripts' folder) reads every PDF again with PyMuPDF's plain `page.get_text()`, shares no code with `parse.py`, and compares the letters and digits of each chapter with those of its files in git. Rebuilding twice from the same files gives the same `git rev-parse HEAD`.
