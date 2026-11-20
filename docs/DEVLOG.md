# Development Log

## 2026-11-20 — M0: machine and repo setup

- Checked the machine: Python 3.12.3 (system, `/usr/bin/python3`), git, Node 24 via nvm, Ollama, Docker.
  Installed `docker-compose-v2` and `gh`; added user to the `docker` group; pulling `llama3.1:8b`.
- Note: Anaconda's Python 3.13 is first on `PATH`; the backend venv is created explicitly from
  `/usr/bin/python3` so it is 3.12 as required by PROJECT_SPEC §5.2.
- Created the local git repository and the folder skeleton from PROJECT_SPEC §25.
- Added `.gitignore` (§25), `.env.example` (§26), a local `.env` with a generated `JWT_SECRET_KEY`
  (gitignored), an empty `corpus/manifest.yaml` (§6.2), README placeholder and CHANGELOG.
- No feature code written; ingestion starts in M1.
- Added UI visual reference: 4 mockups in `docs/images/` and §9.1–9.3 in
  `docs/UI_AND_SYSTEM_OVERVIEW.md` (style tokens + 13 corrections where mockups contradict the
  spec, e.g. role-filtered nav, real embedding model name, no Tier 2 upload button). Landing page
  mockup is style-only; no landing page is built (spec §18.1). No frontend code written (M8).
- `backend/pyproject.toml`: added `asyncio_default_fixture_loop_scope = "function"` (one line beyond
  START_HERE §4.7) to silence the pytest-asyncio deprecation warning and pin per-test event loops.

## 2026-11-20 — M1 step 1–2: config, manifest, public PDFs, fictional SOPs

- `config.py` (pydantic-settings, spec §26) and a validated manifest loader (§6.2/§6.4).
- `download_docs.py` fetched all 7 public PDFs from the URLs in the manifest. WHO had moved its
  file; the current link came from WHO's own publication page. Manifest versions/dates were checked
  against each PDF; FDA/WHO give only a month/year, so the date uses the first day and says so.
- Wrote the 12 fictional SOPs (§6.3), cross-referenced (OOS → deviation → CAPA → change control).
  Every guidance citation in them was checked against the real section headings in the PDFs.
- Learned: FDA guidances number sections `IV.` / `C.` / `2.` — not covered by the §7.2 heading
  patterns. Must be handled (or the spec amended) when building the chunker in step 4.

## 2026-11-20 — M1 step 3: PDF and Markdown loaders

- `pdf_loader.py` (text per page, header/footer stripping, <100-char pages skipped), `md_loader.py`
  (whole file as one page, page=None) and shared `normalize.py` (NFKC, hyphen rejoin, whitespace).
- Bug found by a test: replacing each digit by `#` gives "Page 9" → `#` but "Page 10" → `##`, so
  footers on pages 1–9 never passed the 50% threshold. Fixed by replacing each *run* of digits.
- Real corpus: running titles + page numbers removed from 6/7 PDFs (Annex 11 has none); WHO p60
  skipped. A bare "10" on ICH Q7 p2 is a split date in the history table — correctly kept.
- Limitation (explain-it): a genuine line that repeats at the top/bottom of most pages (e.g. a
  table header on every page) would also be stripped; a lone number at a page edge counts as one.
