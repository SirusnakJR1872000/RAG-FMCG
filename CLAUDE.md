# CLAUDE.md — instructions for Claude working in this repo

## Project
Pharma GMP SOP Assistant: an on-premise RAG web app. Users ask GMP/SOP questions and get cited answers from a controlled, versioned document set. Every action is recorded in a hash-chained audit trail. Stack: FastAPI + SQLite + FAISS/BM25 + cross-encoder reranker + Ollama (llama3.1:8b) + React/Vite/Tailwind v4 + Caddy, delivered with Docker Compose.

## Source of truth
1. `PROJECT_SPEC.md`: what to build. **It always wins.** Never contradict it. If something in it looks wrong, stop and tell me; don't silently deviate.
2. `START_HERE.md`: the order of work (milestones M0–M9) and the done criteria.
3. `docs/UI_AND_SYSTEM_OVERVIEW.md`: screens, components, UI states, data shapes.

Read the relevant spec sections before writing code for a milestone, and cite them (e.g. "per §8.5") when explaining decisions.

## Machine
Ubuntu 24.04, i7-1355U, 16 GB RAM, **CPU only (no GPU)**. Python 3.12. Install PyTorch from the CPU index only: `pip install torch --index-url https://download.pytorch.org/whl/cpu`.

## Rules
- Work only on the milestone or task I give you. Don't start the next one.
- Small steps: build → run → test → show me the result. Don't write large amounts of code without running it.
- Write tests alongside code, not afterwards. Name tests after requirement IDs where relevant (e.g. `test_SEC_04_lockout_after_five_failures`).
- Never use `pickle`, `joblib` or `torch.load` on data files. Use FAISS native format, Parquet and JSON (SEC-11).
- No hardcoded settings: everything goes through `backend/config.py` (pydantic-settings) and `.env`.
- Tests never call the real Ollama. Use `backend/tests/fakes/fake_ollama.py`.
- Never invent numbers (accuracy, latency, gains). Numbers come only from scripts that write to `reports/`.
- Don't run `sudo`. If a system package is missing, tell me the exact command and I'll run it.
- Don't push to GitHub. Make local commits with Conventional Commit messages (`feat(scope): …`, `fix:`, `test:`, `docs:`, `chore:`) when a step works, and show me `git status` and `git log --oneline -5`.
- Don't add dependencies that aren't in spec §5 without asking me first.
- After each task, explain briefly **what** you did, **why** (with spec section), and **how to verify** it. I need to be able to explain every file in an interview, so keep explanations plain.

## Commands
```bash
# backend
cd backend && source .venv/bin/activate
ruff check . && pytest
uvicorn api:app --host 127.0.0.1 --port 8000 --reload

# frontend
cd frontend && npm run dev     # Vite proxies /api → 127.0.0.1:8000
npm run test

# ollama (native, dev)
ollama list
```

## Layout (see PROJECT_SPEC §25 for the full tree)
- `corpus/`: manifest.yaml + fictional SOPs (committed); public PDFs (gitignored)
- `backend/`: api.py, config.py, cli.py, auth/, audit/, database/, routers/, services/, src/{ingestion,retrieval,generation,finetuning,evaluation}/, scripts/, tests/
- `frontend/`: React app
- `data/`, `indexes/`, `models/`: gitignored runtime artefacts
- `reports/`: committed, measured results only

## Current milestone
M0 — machine and repo setup. (Update this line as milestones complete.)
