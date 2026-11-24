# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Project skeleton (PROJECT_SPEC §25), `.gitignore`, `.env.example` (§26), empty corpus manifest (§6.2).
- Backend tooling: Python 3.12 venv with CPU-only PyTorch, ruff and pytest configuration.
- Project specification v6.0, START_HERE tracker and UI/system overview.
- Settings module, validated corpus manifest and public document downloader (M1).
- 12 fictional internal SOPs for Acme Pharma Ltd. (M1).
- PDF loader with header/footer stripping and Markdown loader (M1).
- Section detection and token-bounded chunker; `scripts/build_chunks.py` writes `data/chunks.parquet` (M1).
- Spec v6.2: amendments A-01 to A-03 (§7.1, §7.2).
- Golden evaluation set (50 questions), validator, hit rule and review sheet (M2).
- Retrieval baseline (BM25, FAISS, RRF), evaluation runner and D-11 benchmark; `EMBEDDING_MODEL` set to `intfloat/e5-small-v2` (M3).
- Cross-encoder reranker and D-13 benchmark; `cross-encoder/ms-marco-MiniLM-L-6-v2` confirmed (M4).
- UI prototype (`docs/prototype/`): offline landing page and chat screen with real retrieval data; `scripts/prototype_data.py` exports its data.
