# Evaluation: hybrid-e5-small-v2+rerank-bge-reranker-base (dev)

Git commit `15a499f` · 18 answerable questions (one question = 5.6 points)

| Retriever | Embedding model | Reranker | Hit@1 | Hit@5 | MRR@10 | retrieval p50 ms | rerank p50 / p90 ms |
|---|---|---|---|---|---|---|---|
| hybrid | e5-small-v2 | bge-reranker-base | 0.83 | 0.94 | 0.88 | 28 | 6184 / 6652 |

## Questions not hit in the top 5

- G-010 Does Acme's OOS SOP align with ICH Q7 on investigating out-of-specification results? → top: ACME-SOP-QC-007 §1, ACME-SOP-QC-007 §8, ACME-SOP-QA-005 §2
