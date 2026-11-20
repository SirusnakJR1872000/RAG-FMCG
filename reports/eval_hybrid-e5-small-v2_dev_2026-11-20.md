# Evaluation: hybrid-e5-small-v2 (dev)

Git commit `15a499f` · 18 answerable questions (one question = 5.6 points)

| Retriever | Embedding model | Reranker | Hit@1 | Hit@5 | MRR@10 | retrieval p50 ms | rerank p50 / p90 ms |
|---|---|---|---|---|---|---|---|
| hybrid | e5-small-v2 | — | 0.78 | 0.94 | 0.84 | 14 | — |

## Questions not hit in the top 5

- G-010 Does Acme's OOS SOP align with ICH Q7 on investigating out-of-specification results? → top: ACME-SOP-QC-007 §2, ACME-SOP-QC-007 §0, ACME-SOP-QC-011 §5.4.1–5.4.4
