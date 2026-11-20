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

## 2026-11-20 — M1 step 4: section detection and chunker (spec v6.2)

- Spec amendments approved: A-01 (Roman/letter headings for FDA, `I.1` annex headings, TOC pages
  dropped), A-02 (merged chunks record a range, e.g. `11.14–11.16`), A-03 (digit runs; odd/even
  running headers — WHO alternates `Annex 2` / `WHO Technical Report Series`, each exactly 50%).
- `sections.py`: numbered headings vs numbered paragraphs; guards so footnotes, wrapped numbers,
  numbered lists and reference lists don't become sections. Built against the real corpus, one
  document type at a time (ICH ALL-CAPS chapters, ICH Q7 paragraph numbering 8.31 → 8.3, FDA
  Roman/letter, WHO sentence case, Markdown SOPs).
- Found FDA Part 11 has margin line numbers on every line (76, 77, 78…) — removed in the loader
  when bare numbers count up by one; TOC page references are kept.
- `chunker.py` + `scripts/build_chunks.py`: 681 chunks from 19 documents in ~5 s, max 256 tokens
  with the bge-small tokenizer (special tokens included). 20 random chunks checked by hand: clean.
- Explain-it: sections instead of fixed windows → citations point to a real clause and a chunk
  never mixes two topics; overlap → a sentence cut at a window edge still has its context.

## 2026-11-20 — M2: golden evaluation set (draft, awaiting owner review)

- `backend/tests/golden/golden_set.jsonl`: 50 questions written before any retrieval code —
  30 public / 15 SOP / 5 unanswerable; 20 dev / 30 test; direct, paraphrased, section-specific
  and cross-document styles in both splits. Key facts taken from the source text.
- Unanswerable questions checked absent from the corpus; two are near-misses on purpose
  (ICH Q12 appears only in a Q9(R1) reference list; "particle" only as particle size).
- `src/evaluation/golden.py`: schema, composition rules and the §11.1 hit rule using each
  document's real section tree (ICH Q7 11.15 is under 11.1; WHO 1.10 is NOT under 1.1;
  merged ranges count as each member).
- Integration test proves every expected section exists and is carried by a chunk (no retrieval).
- `docs/golden_review.md` (generated): question + PDF page + source excerpt + checkbox for the
  owner's manual check. Page numbers are PDF page numbers, not printed ones.
- Explain-it: dev/test split → tune on dev only, so test numbers aren't fitted to the test;
  unanswerable questions → measure refusals, the main safety property of a compliance tool.

## 2026-11-20 — M3: baseline retrieval and embedding benchmark (D-11)

- Retrieval: sentence-transformers embeddings with family prefixes (bge instruction, e5
  query:/passage:), FAISS IndexFlatIP (native format + JSON), BM25 rebuilt in memory, RRF k=60.
- The three candidates share the BERT uncased vocabulary: identical token counts on all 681
  chunks, and a byte-identical chunks.parquet under each tokenizer → a fair, same-chunks benchmark.
- Dev results (18 answerable, 1 question = 5.6 pts): all three hybrids Hit@5 0.94; MRR@10
  e5 0.842, bge 0.826, MiniLM 0.746 → rule picks `intfloat/e5-small-v2`. The e5–bge gap is less
  than one question's worth — practically a tie on this small set.
- Hybrid lowers Hit@1 vs dense alone for bge/e5 (BM25 lifts weaker chunks) — reranker (M4) next.
- Explain-it examples: BM25 beats dense on G-013 (exact words "failed login attempts locked");
  dense beats BM25 on G-003 (paraphrase of "Product Quality Review … annually").
  Only hybrid miss in top 5: G-010, a cross-document comparison question (first hit at rank 8).

## 2026-11-20 — M4: reranker (D-13)

- Cross-encoder re-sorts the top-20 hybrid candidates (e5-small-v2). Dev, 18 answerable:
  no reranker Hit@1 0.78 / Hit@5 0.94 / MRR@10 0.84;
  ms-marco-MiniLM-L-6-v2 → 0.94 / 0.94 / 0.95, +787 ms p50 (860 ms p90) per question;
  bge-reranker-base → 0.83 / 0.94 / 0.88, +6,184 ms p50 — over the 2 s budget, excluded.
- D-13 picks ms-marco (it was already the default; now confirmed by measurement).
- Hit@5 can't rise: reranking only re-orders retrieved candidates. G-010 (cross-document
  comparison) moved 8 → 6; its top chunks are SOP references/scope that only *mention* ICH Q7.
- Score scales differ (ms-marco logits vs bge sigmoid) → τ (§8.5) is tuned for ms-marco.
- Latency measured with other apps running (8 of 15 GB RAM in use, load ~1.2).
- Explain-it: bi-encoder = question and chunk encoded separately (vectors precomputed, fast
  search over all chunks); cross-encoder = reads both together (more accurate, but one model
  pass per pair) → only affordable on ~20 candidates, never on the whole corpus.
