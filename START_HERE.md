# START HERE — Pharma GMP SOP Assistant

**Owner:** Gaurav Patil
**Based on:** `PROJECT_SPEC.md` v6.0 (the source of truth — if this file and the spec disagree, the spec wins)
**Machine:** ThinkPad E14 Gen 5 · i7-1355U · 16 GB RAM · Ubuntu 24.04 · CPU only

This is the working document. `PROJECT_SPEC.md` says *what* the finished system looks like; this file says *what to do next, in what order, and how you know each step is done*. Keep it in the repo root and tick boxes as you go.

---

## 1. Rules for building this project

1. **Build in order, finish each milestone before starting the next.** A smaller project that fully works beats a big one that half works.
2. **Measure before you claim.** Every number that goes in the README (Hit@5, latency, fine-tuning gain) comes from a script in this repo, saved in `reports/`.
3. **Commit after every working step.** Small commits with clear messages. Never one giant commit.
4. **You must be able to explain every file.** Each milestone ends with "Explain-it checks". If you can't answer them without notes, the milestone isn't done.
5. **The README only describes what exists.** Unbuilt items go under "Roadmap".

---

## 2. Scope tiers

| Tier | Contents | When |
|---|---|---|
| **Tier 1 — must ship** | Ingestion (section-aware), golden set, hybrid retrieval + reranker, generation with citations, fine-tuned embeddings with honest eval, FastAPI with JWT auth + RBAC, hash-chained audit log, streaming React UI, tests, Docker Compose, CI, README with real results | Milestones M0–M9 |
| **Tier 2 — next** | Document version upload/supersede UI, backup/restore scripts, admin dashboard, feedback review page | After Tier 1 is public |
| **Tier 3 — roadmap only** | Caddy TLS, systemd units, validation templates (URS/IQ/OQ/PQ), SSO | Listed in README as roadmap |

---

## 3. Decisions locked in (summary — full list in PROJECT_SPEC §29)

| Topic | v5 said | Now | Why |
|---|---|---|---|
| Python | 3.11 | **3.12** | Ubuntu 24.04 default; all dependencies support it |
| Corpus | 5 public guidance PDFs | **+ FDA Part 11 guidance, EU GMP Annex 11, + 12 synthetic internal SOPs** | Part 11 questions need Part 11 sources; on-prem story needs internal SOPs |
| Chunking | fixed 500 chars | **section-aware** (numbered headings), **≤ 256 tokens** (≈ 900–1000 chars), 48-token overlap, header/footer stripped, section number in metadata | Citations like "ICH Q7 §8.1"; no candidate embedding model truncates a chunk |
| Embedding model | MiniLM assumed | **benchmark MiniLM vs bge-small-en-v1.5 vs e5-small-v2**, pick on data | Answer to "why this model?" |
| Reranker | none | **cross-encoder on top-20** (`BAAI/bge-reranker-base` or `cross-encoder/ms-marco-MiniLM-L-6-v2`) | Standard in modern RAG |
| Fine-tuning data | BM25-mined chunk pairs | **LLM-generated (question, chunk) pairs** | Realistic queries; avoids teaching the model to copy BM25 |
| Fine-tuning eval | on training pairs (leakage) | **on held-out golden test split only** | Honest numbers |
| Index storage | pickle | **FAISS native + Parquet/JSON metadata; BM25 rebuilt at startup** | Pickle can execute code on load |
| LLMs | llama3.1:8b for everything | **llama3.1:8b is the only model loaded while serving** (answers + follow-up rewrite). **llama3.2:3b only for offline question generation.** `num_ctx=4096` set on every call | Two resident models would overflow 16 GB RAM; Ollama's default context can silently truncate prompts |
| Citations | `[Source: file, Page X]` | **numbered `[n]`** mapped to the source panel | Easier for an 8B model; checkable by code |
| Follow-ups | none | **standalone-question rewrite using last 2 turns** | Multi-turn chat |
| Faithfulness | citation check only | **+ local LLM judge on test split + 30 manually reviewed answers** | "How do you know answers are faithful?" |
| Packaging | systemd + Caddy | **Docker Compose (Tier 1) with Caddy as the web container** (serves React, TLS, proxies `/api`); systemd → Tier 3 | Reviewers expect `docker compose up`; HTTPS comes for free |
| CI | none | **GitHub Actions: ruff + pytest** | Cheap professionalism signal |

---

## 4. Milestone M0 — Machine and repo setup (½ day)

### 4.1 System packages
```bash
sudo apt update
sudo apt install -y git build-essential python3-venv python3-pip curl jq
python3 --version          # expect 3.12.x
```

### 4.2 Node.js (via nvm)
```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/master/install.sh | bash
source ~/.bashrc
nvm install --lts
node -v && npm -v
```

### 4.3 Ollama + models
```bash
curl -fsSL https://ollama.com/install.sh | sh     # installs a systemd service on 127.0.0.1:11434
ollama pull llama3.2:3b                           # ~2.0 GB — offline question generation only
ollama pull llama3.1:8b                           # ~4.9 GB — answers
ollama run llama3.2:3b "Say OK"                   # sanity check
```

### 4.4 GitHub CLI and Docker
```bash
sudo apt install -y gh docker.io docker-compose-v2
sudo usermod -aG docker $USER     # log out and back in after this
gh auth login
```

### 4.5 Create the repo
```bash
mkdir -p ~/projects/pharma-gmp-rag && cd ~/projects/pharma-gmp-rag
git init -b main

mkdir -p backend/{src/{ingestion,retrieval,generation,finetuning,evaluation},auth,audit,database,routers,services,scripts,tests/{unit,integration,security,fakes,golden}}
mkdir -p frontend corpus/{public,sops,archive} data indexes models reports docs/{images,archive} deploy/caddy .github/workflows
touch backend/src/__init__.py backend/src/{ingestion,retrieval,generation,finetuning,evaluation}/__init__.py
touch backend/{auth,audit,database,routers,services}/__init__.py
```

> Note: PDFs live in `corpus/`, and `docs/` is for project documentation (README images, user guide). This avoids the v5 naming clash.

### 4.6 Python environment (CPU-only PyTorch)
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip

# CPU wheel — the default Linux wheel pulls ~3 GB of CUDA libraries you can't use
pip install torch --index-url https://download.pytorch.org/whl/cpu

pip install pymupdf sentence-transformers faiss-cpu rank-bm25 pyarrow pandas \
            requests tqdm numpy fastapi "uvicorn[standard]" pydantic-settings \
            sqlalchemy pyjwt argon2-cffi slowapi structlog python-multipart pyyaml
pip install pytest pytest-asyncio pytest-cov httpx ruff

pip freeze > requirements.lock     # exact versions you actually ran
```
Then write a short, hand-curated `requirements.txt` (direct dependencies only) and `requirements-dev.txt`.

### 4.7 Base files

**`.gitignore`**
```gitignore
.env
corpus/public/
data/
indexes/
models/
reports/*.tmp
__pycache__/
*.pyc
.venv/
.pytest_cache/
.coverage
.ruff_cache/
frontend/node_modules/
frontend/dist/
.DS_Store
```
> `corpus/sops/` (your synthetic SOPs) **is** committed — you wrote them. Public PDFs are not; `download_docs.py` fetches them. `reports/` is committed so results are visible on GitHub.

**`backend/pyproject.toml`**
```toml
[project]
name = "pharma-gmp-rag"
version = "0.1.0"
requires-python = ">=3.12"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "S"]   # S = security checks (flags pickle, asserts, etc.)
ignore = ["S101"]                          # allow assert in tests

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-q"
```

**`.env.example`** — copy the block from PROJECT_SPEC §26 exactly.

### 4.8 First commit and push
```bash
cd ~/projects/pharma-gmp-rag
cp ~/Downloads/PROJECT_SPEC.md ~/Downloads/START_HERE.md .
cp ~/Downloads/UI_AND_SYSTEM_OVERVIEW.md docs/
cp ~/Downloads/pharma_rag_project_plan_v*.md docs/archive/   # history only
git add .
git commit -m "chore: initial project skeleton, tooling config, project spec v6.0"
gh repo create pharma-gmp-rag --public --source=. --push
```

### ✅ M0 done when
- [ ] `ollama run llama3.1:8b "hi"` replies
- [ ] `python -c "import torch, faiss, sentence_transformers; print(torch.__version__)"` works and shows `+cpu`
- [ ] `ruff check backend` runs, and `pytest` runs (0 tests is fine)
- [ ] Repo is on GitHub with the skeleton and plan

---

## 5. Milestones M1–M9

Rough effort assumes 2–3 focused hours a day.

### M1 — Corpus and ingestion (3–4 days)

**Build**
- `scripts/download_docs.py`: fetch ICH Q7, ICH Q9(R1), ICH Q10, FDA Process Validation (2011), WHO GMP main principles, FDA *Part 11, Electronic Records; Electronic Signatures — Scope and Application* guidance, EU GMP Annex 11. Download from the official ich.org, fda.gov, who.int and health.ec.europa.eu pages; if a URL fails, download by hand into `corpus/public/`.
- `corpus/sops/`: 12 synthetic SOPs in Markdown for a fictional company, e.g. *"Acme Pharma — SOP-QA-014 Deviation Management"*, *SOP-QC-007 OOS Investigation*, *SOP-QA-021 Change Control*, *SOP-IT-003 Audit Trail Review*. Every file starts with: `FICTIONAL DOCUMENT — created for demonstration`. Give each a document number, version, effective date and numbered sections.
- `src/ingestion/pdf_loader.py`: extract text per page; strip repeated headers and footers (lines that appear on > 50% of pages).
- `src/ingestion/md_loader.py`: load SOP Markdown with the same output shape.
- `corpus/manifest.yaml`: one entry per document (spec §6.2). Ingestion refuses files not listed.
- `src/ingestion/chunker.py`: split on numbered headings (`8.1`, `8.1.2`, `5.`), merge small sections, split long sections at sentence boundaries. **Count length with the embedding model's tokenizer: ≤ 256 tokens, 48-token overlap.** Record fields exactly as spec §7.4.
- `scripts/build_chunks.py` → `data/chunks.parquet`.

**Tests**: heading detection, header/footer removal, no chunk > max size, every chunk has a section and page.

**✅ Done when**: you open `chunks.parquet` in pandas, sample 20 random chunks, and every one is clean text with a correct section number.

**Explain-it checks**
- Why split on sections instead of fixed character windows?
- How does your header/footer removal decide what to strip, and when could it remove real content?
- Why overlap when splitting long sections?

**Commits**: `feat(ingestion): pdf loader with header/footer stripping` · `feat(ingestion): section-aware chunker` · `feat(corpus): add 12 fictional internal SOPs`

---

### M2 — Golden evaluation set (2 days) — do this BEFORE building retrieval

Writing questions after you've seen what retrieval returns biases the test. Write them now.

**Build**: `tests/golden/golden_set.jsonl` — 50 questions:
- 30 on public guidance, 15 on your SOPs, 5 that **no document answers** (to test refusals)
- Mix of styles: direct ("What is a PQR?"), paraphrased ("how often do we need to review product quality?"), section-specific ("What does ICH Q7 say about reprocessing?"), cross-document ("Does SOP-QC-007 align with ICH Q7 on OOS?")
- Each line: `id, split, answerable, question, expected: [{doc_code, section}], key_facts` (format in spec §11.1)
- Split: **20 `dev`** (tune on these) / **30 `test`** (only for final numbers — never look at failures here while tuning)

**✅ Done when**: 50 lines, each expected section checked by opening the document yourself.

**Explain-it checks**
- Why separate dev and test splits?
- Why include unanswerable questions?

---

### M3 — Baseline retrieval + model benchmark (3–4 days)

**Build**
- `src/retrieval/embeddings.py`: load any sentence-transformers model by name; handle the e5 `query: ` / `passage: ` prefixes and bge's query instruction.
- `src/retrieval/faiss_store.py`: `faiss.write_index` / `read_index`; metadata stays in `chunks.parquet` matched by row order and `chunk_id`.
- `src/retrieval/bm25_store.py`: built in memory at startup from `chunks.parquet` (no pickle).
- `src/retrieval/hybrid.py`: RRF with k = 60.
- `src/evaluation/metrics.py`: Hit@1, Hit@5, MRR@10 at **section** level.
- `scripts/run_eval.py --split dev --retriever {bm25,dense,hybrid} --model <name>` → `reports/eval_<date>_<config>.json` and a Markdown table.

**Benchmark** on `dev`: BM25 alone, then dense and hybrid each with `all-MiniLM-L6-v2`, `BAAI/bge-small-en-v1.5` and `intfloat/e5-small-v2`. Pick the best base model based on these results.

**✅ Done when**: `reports/model_benchmark.md` has the table, and you've written two sentences on why you picked the winner.

**Explain-it checks**
- Why normalise vectors and use inner product?
- What does RRF do, and why does k = 60 work without tuning?
- When does BM25 beat dense retrieval in your own results? Show a real example.

---

### M4 — Reranker (1–2 days)

**Build**: `src/retrieval/reranker.py` — a cross-encoder scores the top 20 hybrid results and keeps the top 5. Add `--rerank` to `run_eval.py`.

**✅ Done when**: you have dev results with and without the reranker, plus the added latency in ms on your laptop.

**Explain-it check**: What's the difference between a bi-encoder and a cross-encoder, and why not use the cross-encoder for everything?

---

### M5 — Generation and CLI (3–4 days)

**Build**
- `src/generation/ollama_client.py`: blocking + streaming, timeout, clear error if Ollama is down. One shared `httpx` client. **Always pass `num_ctx: 4096`.**
- `src/generation/prompts.py`: prompt exactly as spec §9.3 — numbered sources inside `<sources>`, `NOT_COVERED` instruction.
- `src/generation/rewriter.py`: standalone rewrite of follow-ups using the last 2 turns, on **llama3.1:8b** (the only model loaded while serving). Optional expansion stays off unless it passes gate D-14.
- `src/generation/citation_check.py`: every `[n]` must be between 1 and the number of sources; an answer with no citations is flagged.
- `src/generation/pipeline.py`: one class `RagPipeline` created **once** (models and indexes loaded in `__init__`); method `answer(question, history) -> Result`.
- Refusal path: if the top reranker score is below a threshold, return "not covered" without calling the LLM.
- `backend/cli.py`: interactive CLI chat loop with streaming output.
- `scripts/tune_threshold.py`: choose the reranker-score threshold τ on dev (spec §8.5) → `reports/threshold.md`.
- `scripts/measure_latency.py`: runs 10 dev questions and records each stage's time → `reports/latency.md`.

**Tests** (with `tests/fakes/fake_ollama.py`): citation parser, refusal path, follow-up rewrite called only when history exists.

**✅ Done when**: you can hold a 3-turn conversation in the CLI with correct citations, and `reports/latency.md` has **measured** numbers.

**Explain-it checks**
- How does the prompt keep the model from answering outside the context, and how do you know when it fails?
- Why is only one LLM loaded while the app is serving, and why must `num_ctx` be set explicitly?
- Why does the refusal threshold use the reranker score and not the RRF score?

---

### M6 — Fine-tuning the embedding model (3–4 days, plus ~3–5 h of unattended CPU time)

**Build**
- `src/finetuning/generate_queries.py`: for each chunk, ask llama3.2:3b for 3 questions a QA engineer might ask that this chunk answers → `data/train_pairs.jsonl`. Apply the filters and round-trip check in spec §10.2. Exclude every chunk in the same section as an expected answer for a **test**-split question (prevents leakage). Run overnight, with the web app stopped.
- `src/finetuning/train_embeddings.py`: settings exactly as spec §10.3 (MNRL, batch 32, 2 epochs, lr 2e-5, seed 42); save to `models/pharma-<base>-v1/` with `training_config.json`.
- **Decide** adoption on the **dev** split (rule in spec §10.4); then **report** base vs fine-tuned once on the **test** split → `reports/finetune_results.md`.

**✅ Done when**: the results table exists, whatever the numbers are. If fine-tuning doesn't help, write down why you think so; that's still a good interview answer.

**Explain-it checks**
- How does MultipleNegativesRankingLoss create negatives, and why does batch size matter?
- How did you stop test questions from leaking into training?
- What would you try next if the gain were small?

**Commit**: `feat(finetune): synthetic query generation + MNRL training; results in reports/`

---

### M7 — Backend API, auth and audit (6–8 days)

Follow PROJECT_SPEC §12–§17 and §19. Tier 1 contents:
- `config.py` (pydantic-settings, fails fast on placeholder secret)
- `database/`: users, documents (registry populated by ingestion; no upload UI yet), audit_log with triggers, feedback, refresh_tokens
- `auth/`: Argon2id, JWT access + rotating refresh cookie, lockout, `require(permission)`
- `audit/`: single `log()` writer with a lock, hash chain, `verify()`
- `routers/`: auth, query (blocking + streaming `POST`), history, documents (read-only), audit (log, export, verify), users, feedback, health
- `services/llm_queue.py` (semaphore = 1, queue position events)
- FastAPI `lifespan` builds `RagPipeline` once
- `scripts/create_admin.py`

**Tests** (most important in the project):
- [ ] login success/fail, lockout after 5, expired and forged token rejected
- [ ] each role gets 403 on each forbidden endpoint (parametrised from the permission matrix)
- [ ] every action writes exactly one audit event with the right user
- [ ] `UPDATE`/`DELETE` on `audit_log` raises
- [ ] editing a row's JSON directly makes `verify()` fail at that `seq`
- [ ] streaming endpoint emits `sources` → `token`… → `done`, in that order

**✅ Done when**: `pytest --cov` passes with ≥ 80% on backend code and 100% on `audit/`, and the OpenAPI docs at `/docs` show all endpoints.

**Explain-it checks**
- Why keep the access token in memory and the refresh token in an httpOnly cookie?
- What does the hash chain catch that triggers don't, and what can neither of them stop?
- Why can't `EventSource` be used here?

---

### M8 — React frontend (5–7 days)

```bash
cd frontend
npm create vite@latest . -- --template react
npm install react-router-dom
npm install -D tailwindcss @tailwindcss/vite vitest @testing-library/react jsdom @playwright/test
```
Configure the Vite dev proxy: `/api` → `http://127.0.0.1:8000`.

**Build, in this order**: `AuthProvider` + login page → chat page with `useStreamingQuery` → source panel → history page → documents page → audit page (auditor view with "Verify integrity") → user admin page → feedback buttons.

**Tests**: Vitest for the stream parser and auth refresh; one Playwright test: login → ask → see streamed answer and sources → auditor sees the event.

**✅ Done when**: a viewer, a qa_user and an auditor each see only their own menus, and the Playwright test passes.

---

### M9 — Packaging and public release (2–3 days)

- `docker-compose.yml`: `ollama` (named volume for models), `backend`, `web` (Caddy serving the built React app, TLS, proxying `/api`; config in `deploy/caddy/Caddyfile`). Only `web` publishes ports. One-time setup via `docker compose run --rm backend python scripts/setup.py` (spec §24.1).
- `.github/workflows/ci.yml`: ruff + pytest (with fake Ollama) on every push; badge in README.
- `README.md`:
  1. One-paragraph problem statement + intended use
  2. Architecture diagram (PNG in `docs/images/`)
  3. 60-second screen recording (GIF or linked video)
  4. **Results**: model benchmark, reranker gain, fine-tuning gain, faithfulness check, measured latency — all linking to `reports/`
  5. Quickstart: `docker compose up` and a local dev setup
  6. Security & compliance summary (link to the plan's §17), using "designed to support" language
  7. Limitations and roadmap (Tier 2 + Tier 3)
- Pin the repo on your GitHub profile.

**✅ Done when**: a fresh clone on another machine (or a new user account on yours) reaches a working login page by following only the README.

---

## 6. Existing draft code — what to do with it

The files drafted earlier are a reference, not final code. Rewrite them in the milestones above with these changes:

| Draft file | Action |
|---|---|
| `pdf_loader.py` | Keep the core; add header/footer stripping (M1) |
| `chunker.py` | Replace with the section-aware version (M1) |
| `pair_generator.py` | Replace with `generate_queries.py` (M6) |
| `train_embeddings.py` | Keep the training loop; **remove the evaluation on training pairs**; evaluate on the test split instead (M6) |
| `embeddings.py` | Generalise for any model and handle prefixes (M3) |
| `faiss_store.py`, `bm25_store.py` | Remove pickle (M3) |
| `hybrid_retriever.py` | Keep the RRF logic; key on `chunk_id`, not chunk text (M3) |
| `ollama_llm.py` | Fix the missing `f` in the connection error message; switch to a shared `httpx` client (M5) |
| `query_rewriter.py` | Becomes `rewriter.py`: follow-up rewrite on llama3.1:8b; HyDE kept behind the D-14 gate (M5) |
| `rag_chain.py` | Replace with the `RagPipeline` class that loads once (M5) |

---

## 7. Daily routine

1. Open this file and pick the next unticked item.
2. Write the test first if the item has clear inputs and outputs.
3. Build → run → `ruff check` → `pytest`.
4. Commit with a conventional message: `feat(scope): …`, `fix(scope): …`, `test(scope): …`, `docs: …`, `chore: …`.
5. Push.
6. Write 2–3 lines in `docs/DEVLOG.md`: what you did, what broke, what you learned. These notes become your interview stories.

---

## 8. Master checklist

- [ ] M0 Setup and repo
- [ ] M1 Corpus and ingestion
- [ ] M2 Golden set (50 questions, dev/test split)
- [ ] M3 Retrieval baseline + model benchmark
- [ ] M4 Reranker
- [ ] M5 Generation + CLI + measured latency
- [ ] M6 Fine-tuning with honest test-split results
- [ ] M7 API, auth, audit + tests
- [ ] M8 React frontend + tests
- [ ] M9 Docker Compose, CI, README, pinned on GitHub
- [ ] Explain-it checks answered aloud for every milestone

---

## 9. Your first session (today, ~2 hours)

1. Do M0 §4.1–4.3 (packages, Node, Ollama + both models; the model downloads can run in the background).
2. Do §4.5–4.7 (skeleton, venv with CPU PyTorch, config files).
3. First commit and push (§4.8).
4. Start M1: run `download_docs.py` or download the 7 PDFs by hand into `corpus/public/`.
5. Write the first fictional SOP (`SOP-QC-007 OOS Investigation`) so you have the format settled.

Next session: the PDF loader with header/footer stripping.
