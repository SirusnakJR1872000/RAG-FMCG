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

## 2026-11-24 — UI prototype (design preview, not M8)

- `docs/prototype/`: self-contained landing page + chat screen following the mockups in
  `docs/images/` (no CDN, works offline, responsive from phone to 1920 px). Photos are cropped
  from the mockup; everything else is real data exported by `backend/scripts/prototype_data.py`:
  19-document registry, hybrid + reranker results for dev questions, benchmark numbers.
- Typed questions run BM25 over the real 681 chunks in the browser (checked equal to the
  backend's BM25). Answers are not generated — marked "Sample answer · LLM in M5".
- Features not built yet carry tags (M7 audit trail/roles, Tier 2 upload, Roadmap FMCG/GMA).
- Dev questions only, so the test split stays unseen (§11.1).

## 2026-11-24 — M5: generation and CLI

- Built (spec §8–§9, §17): async Ollama client (num_ctx 4096 on every call, typed errors for
  Ollama down / model missing / timeout), grounded prompt exactly as §9.3, citation check,
  follow-up rewriter, `RagPipeline` (stream() yields the §17 events, answer() returns a Result),
  streaming CLI, `tune_threshold.py`, `measure_latency.py`, fake Ollama for tests (~380 tests).
- **τ = -5.34** (reports/threshold.md). Dev: refusal 1 of 2, false refusals 0 of 18. The ICH Q12
  near-miss (G-018) scores +2.8 on the reranker — higher than a genuine answerable question
  (G-007, -1.7) — so no τ can refuse it within the 5 % false-refusal rule. In the real CLI the
  model's own NOT_COVERED caught it; the Grade A question was refused with no LLM call (1 s).
- **Real-model findings** (things the fake Ollama could not show):
  1. The rewriter copied labels ("ACME-SOP-QC-007 §1 Purpose (v3.0)") from the previous answer
     into the next question → search for the label → false NOT_COVERED. Fixed: prompt, citation
     markers hidden in previews, rewrites containing §/[n]/(v3.0)/unknown doc codes rejected.
  2. The rewriter paraphrased self-contained questions and drifted to the previous topic
     ("Annex 11 … audit trails" → "… OOS documentation"). Probe on the real model: rank-1 hits
     0/5 → 4/5 after "change as little as possible" + rewrite only questions that refer back.
  3. Ollama caches processed prompts: an identical repeated question had a 1.4 s first token vs
     ~38 s cold. measure_latency now unloads the model first.
  4. Answers sometimes paste the source label ("According to [1] ACME-SOP-QC-007 §1 …"), and in
     one turn put a wrong label next to a valid [n]. The citation check validates numbers only;
     faithfulness is for the §11.2 evaluation. The §9.3 prompt is fixed by the spec, so prompt
     changes would need an amendment.
- **Latency** (reports/latency.md; busy laptop: 3.5 GB RAM free, 3 GB swap in use): retrieval
  110 ms ✓, rerank 789 ms ✓, full answer p50 51 s ✓ (target 90), first token p50 38.7 s ✗
  (target 30), 6 tokens/s. Memory: backend 1.0 GB, Ollama 5.3 GB. Prompts max 1,218 of 4,096
  tokens. The §20 remedies (3 chunks, num_predict 300, …) were NOT applied: the miss was
  measured under memory pressure and must be re-measured on a quiet machine first. That report
  predates fix 2 above (its scripted turn 2 hit the refusal bug).
- Explain-it: the prompt confines the model to <sources> and gives it NOT_COVERED, the citation
  check and (later) the faithfulness judge show when it fails; one LLM at serving time because
  2 would not fit 16 GB, and num_ctx is explicit because Ollama's default can truncate silently;
  τ uses the reranker score because RRF scores depend only on rank positions.

## 2026-11-25 — M7: backend API, authentication and audit

- Built (spec §12–§17, §19, §24.1): SQLite schema as SQLAlchemy Core with the audit triggers and
  the one-active-version index; hash-chained audit trail with a single `log()` writer and
  `verify()`; Argon2id passwords with the §13.2 policy; JWT access tokens (HS256 only, role
  re-read from the database on every request); rotating refresh tokens with reuse detection and
  an Origin check; lockout; the §13.3 permission matrix; FastAPI app with a uniform error body,
  request ids and rate limits; one-at-a-time LLM queue; blocking and SSE query endpoints;
  history (read from the audit events), feedback, documents, audit log/verify/export, users,
  health; `scripts/create_admin.py` and `scripts/setup.py`.
- **Measured** (pytest --cov, backend/): 818 tests collected, all passing; coverage 91 % overall,
  100 % on `audit/` (done criteria: ≥ 80 % and 100 %). `/docs` lists every Tier 1 endpoint.
  Not yet done: a run against the real index and Ollama (the training job was using the memory).
- Decisions worth knowing:
  1. History has no table: it IS the QUERY / QUERY_FAILED audit events, so it cannot disagree
     with the audit trail. The audit event is written before the `done` SSE event; if the browser
     disconnects, a `completed: false` event is written in a `finally` block.
  2. Service functions return statuses rather than raising, so failure counters and session
     revocations are committed instead of rolled back with the request.
  3. `USER_UNLOCKED` is not in the §14.2 catalogue but FR-11 needs unlocking; it is recorded
     as proposed amendment A-04 and PROJECT_SPEC.md has NOT been edited.
  4. There is no `GET /conversations`: the UI derives the list from `/history` (§16 lists none).
  5. The client IP in the audit trail comes from uvicorn's proxy headers; M9 must start uvicorn
     with `--proxy-headers --forwarded-allow-ips` for the Caddy container.
  6. CSV export, document upload and withdrawal are Tier 2 and not built.
- Mistake caught: a setup-script test wrote into the real `corpus/manifest.yaml` (the `settings`
  fixture points at the real corpus). Restored from git; that test file now uses a temporary
  corpus directory.
- Explain-it: a permission is checked by the server on every call, never by hiding a menu; the
  chain hash covers the previous row's hash, so editing any row breaks every later link and
  `verify()` names the first broken `seq`; refresh tokens rotate so a stolen copy is detected
  the moment both copies are used.

## 2026-11-25 — M6: fine-tuning result (D-12)

- Trained `models/pharma-e5-small-v2-v1` (1,594 pairs, 2 epochs, 100 steps, 25 min on CPU);
  validation loss 2.05 → 0.15. Report: `reports/finetune_results.md`.
- **Decision: do not adopt** (§10.4, dev split, full pipeline): dev Hit@5 0.944 and MRR@10 0.954
  for both models: no question changed rank. `EMBEDDING_MODEL` stays `intfloat/e5-small-v2`.
- Test (reported once, not used): Hit@5 0.926 → 0.963 (one question, G-048, rank 6 → 5), MRR@10
  0.848 → 0.849: within the one-question noise.
- Worth explaining: WITHOUT the reranker the fine-tuned model is clearly worse (dev Hit@1 0.778
  → 0.556, MRR@10 0.842 → 0.705). The validation loss measures matching generated questions to
  their own chunk, which the model learned; it does not measure ranking among near-duplicate
  GMP passages for human questions. Likely causes: llama3.2:3b questions copy the chunk's words,
  and 1,594 pairs from 617 chunks over-fit a 33M-parameter model. The reranker hides the damage.

## 2026-11-25 — M8: React frontend

- Built (spec §5.1, §17, §18; design brief §4–§9): Vite + React 19 + React Router + Tailwind v4
  with the §9.2 tokens; login, forced/voluntary password change, app shell (role-filtered nav,
  status pill, user menu, integrity/system/session-expiry banners, toasts), Chat (conversation
  list, streaming answer in all 11 states, clickable citations, source panel, feedback, copy),
  History (filters, detail drawer with "Superseded" tags), Documents (summary strip, filters,
  detail drawer with SHA-256 and version history), Audit (integrity panel + Verify now, grouped
  event filters, detail drawer with readable payload / raw JSON / hashes, JSON export with
  confirmation), Users (add with one-time temporary password, change role, unlock, deactivate),
  System health drawer (admin).
- Packages: only those in START_HERE M8 (plus what the Vite template brings). Icons are inline
  SVG, fonts are the system stack: no icon library, no font CDN (§9.2, on-premise).
- **Measured:** Vitest 37 tests (stream parser incl. every chunk split, silent refresh incl.
  one shared refresh for parallel 401s, the answer state machine, menus by role, Users guards);
  Playwright 2 tests against the real API with the fake pipeline (`backend/tests/e2e_server.py`):
  viewer asks → sources then streamed answer → citation highlights its source → feedback →
  History; qa_user and auditor see only their menus; auditor sees the QUERY event and verifies
  the chain; admin sees all menus; a reload restores the session from the cookie; sign-out
  revokes it. Production bundle 343 kB JS (105 kB gzip).
- Decisions:
  1. Access token in memory only; parallel 401s share ONE refresh call, because refresh tokens
     rotate and a second use of the old one would trip the server's reuse detection (§13.1).
  2. The conversation list is built from `GET /history` (no conversations endpoint, §16).
  3. The auditor's integrity panel says "not checked yet" until they press Verify now, because
     the last result is in `/health/details`, which is admin-only; verifying is itself audited.
  4. Non-admins see three summary cards on Documents: the index build date and embedding model
     come from `/health/details` (admin-only), so for others the third card is "Last ingested".
  5. Two oxlint rules are off: `only-export-components` (dev hot-reload only; pages export small
     helpers the tests use) and `set-state-in-effect` (the "reset to loading, then fetch" pattern).
- Dev setup: the backend's `SITE_ORIGIN` must be `http://localhost:5173` when using the Vite dev
  server, or refresh and logout are refused (Origin check, §13.1). Documented in `.env.example`.
