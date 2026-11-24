# UI prototype (design preview — not the M8 app)

Landing page + chat screen in the style of `docs/UI_AND_SYSTEM_OVERVIEW.md` §9.
Retrieval results are **real**: example questions show the full pipeline output
(hybrid e5-small-v2 + BM25 → RRF → ms-marco reranker), exported by
`backend/scripts/prototype_data.py`; typed questions run BM25 over the real chunks in the
browser (identical results to the backend's BM25). Answer generation, login and the audit
trail are not built yet (M5, M7).

```bash
cd docs/prototype && python3 -m http.server 8080 --bind 127.0.0.1   # then open http://127.0.0.1:8080
# refresh the data after re-chunking or changing models:
cd backend && source .venv/bin/activate && python -m scripts.prototype_data
```
