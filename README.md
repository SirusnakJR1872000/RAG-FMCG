# Pharma GMP SOP Assistant

A web application where authorised users ask questions in plain English and receive answers that are:
- drawn **only** from a controlled, versioned set of documents,
- **cited** to document, version, section and page,
- produced **entirely on-premise** (LLM, embeddings, indexes and database on one machine),
- **attributable**: every use is recorded in a tamper-evident audit trail with the user's identity.

**Status: under construction — see [PROJECT_SPEC.md](PROJECT_SPEC.md).**

# terminal 1: backend (first time only: python -m scripts.setup to create your admin)
cd backend && source .venv/bin/activate
SITE_ORIGIN=http://localhost:5173 uvicorn api:app --host 127.0.0.1 --port 8000
# terminal 2: frontend
cd frontend && npm run dev        # open http://localhost:5173
# tests
npm run test                      # Vitest
npm run e2e                       # Playwright (starts its own servers)