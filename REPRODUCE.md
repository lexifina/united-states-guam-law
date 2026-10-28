# Reproducing this repository

Built on 2026-10-29 from the Guam Code Annotated PDFs retrieved 2026-10-28, by the scripts in `tools/build/` (copied there as run). [`data/source-sha256.tsv`](data/source-sha256.tsv) lists the sha256 of the index page and of each PDF the build read, so a copy of those files can be checked byte for byte before rebuilding. How the files were retrieved is not part of this record.

| Script | sha256 |
| --- | --- |
| parse.py | `4914a5c906b1a55f2e4cad27cbf665ae9584d3c2274ba32c9b7b365ecf1ca58d` |
| build.py | `d9cf116c615330e87b252b9516ed5020c0264be6a79dc1a69a7e9418cd259425` |
| docs.py | `d786fffba435298f1bd7c7e3ffe45633ed48e05c0975cd1b4f58ebf738ac292a` |
| check_words.py | `7b7b38dd5bdc9d194062bce51df8508e4f81bdb726e1bb4eef527ae596d7cdf4` |
| asciify.py | `f77a135b1da24a3a706474a607df9948d62ee0ee52d268473675395ad0b340c3` |

Python 3.10 or later, PyMuPDF (`pip install pymupdf`) and git.

## Steps

With the retrieved index page and chapter PDFs in place (each matching its sha256 in `data/source-sha256.tsv`), and the day each was retrieved:

```sh
# 1. Read each PDF into paragraphs. Run it in one process: a pool of workers died twice on the build machine.
#    About 4 minutes.
python parse.py --workers 1
# 2. Build into a new, empty folder. --today dates the build and is the latest date allowed.
python build.py ../united-states-guam-law-build --today 2026-10-29
```

With the same files, `build.py` gives the same commit hashes, because it writes the whole history in one `git fast-import` stream, sorted, with fixed dates and messages written as bytes.

## What the build produced

- 824 chapters (and divisions, parts, appendices and attachments) from 22 titles: 10,397 pages.
- 18,663 text files: 17,839 sections, rules and forms, plus a `chapter.md` per chapter for its front matter. 35 chapters print no section and are held whole in `chapter.md`.
- 825 commits: 824 consolidated (one per chapter) and one documentation commit.
- Compilation dates from 2006-06-30 to 2026-10-28: 820 from the Compiler's page stamps, 4 from the retrieval day.
- 13,546 public-law citations in the SOURCE notes, of 3,173 public laws (`data/amendments.csv`).

## Checks

```sh
python ../lexifina/scripts/global-law/check_corpus.py .     # the shared preflight
git rev-list --merges --count main                          # 0
git log --format='%(trailers:key=In-force,valueonly)' main | grep . | sort -c -r   # dates never go back
git log --format=%B main | grep -c $'\r'                    # 0
python tools/in_force_on.py 2026-10-29 "1 GCA 1607"
python tools/in_force_on.py 2026-10-29 "6 GCA Rule 401"
```

The letters-and-digits check (`check_words.py` in the build scripts' folder) reads every PDF again with PyMuPDF's plain `page.get_text()`, shares no code with `parse.py`, and compares the letters and digits of each chapter with those of its files in git. Rebuilding twice from the same files gives the same `git rev-parse HEAD`.
