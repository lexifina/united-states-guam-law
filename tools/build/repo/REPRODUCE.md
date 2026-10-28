# Reproducing this repository

Built on {{TODAY}} from the Guam Code Annotated PDFs retrieved {{RETRIEVED}}, by the scripts in `tools/build/` (copied there as run).

| Script | sha256 |
| --- | --- |
| fetch.py | `{{SHA_FETCH_PY}}` |
| parse.py | `{{SHA_PARSE_PY}}` |
| build.py | `{{SHA_BUILD_PY}}` |
| docs.py | `{{SHA_DOCS_PY}}` |

Python 3.10 or later, PyMuPDF (`pip install pymupdf`), git and curl.

## Steps

```sh
# 1. The index page and every chapter PDF it links (847 PDFs, about 142 MB; resumable, cached under .cache/).
python fetch.py
# 2. Read each PDF into paragraphs (.cache/parsed/<pdf>.json). Run it in one process: a pool of workers
#    died twice on the build machine. About 4 minutes.
python parse.py --workers 1
# 3. Build into a new, empty folder. --today dates the build and is the latest date allowed.
python build.py ../united-states-guam-law-build --today {{TODAY}}
```

## robots.txt, terms and bulk data


## Fetch rate

robots.txt sets no Crawl-delay. `fetch.py` runs one process with at most 4 requests open at a time to `col.guamcourts.gov`, and fetched the 847 PDFs once, on {{RETRIEVED}}, with no errors. A failed request is retried up to 4 times, waiting 3, 6, 9 and 12 s. A 404 is recorded and not asked again. The scripts call `curl --compressed` and keep every file under `.cache/` (git-ignored). [`data/source-sha256.tsv`](data/source-sha256.tsv) lists the sha256 of the index page and of each PDF. With the same files, `build.py` gives the same commit hashes, because it writes the whole history in one `git fast-import` stream, sorted, with fixed dates and messages written as bytes.

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

The letters-and-digits check (`check_words.py` in the build scripts' folder) reads every PDF again with PyMuPDF's plain `page.get_text()`, shares no code with `parse.py`, and compares the letters and digits of each chapter with those of its files in git. Rebuilding twice from the same cache gives the same `git rev-parse HEAD`.
