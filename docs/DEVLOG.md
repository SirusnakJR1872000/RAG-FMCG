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
