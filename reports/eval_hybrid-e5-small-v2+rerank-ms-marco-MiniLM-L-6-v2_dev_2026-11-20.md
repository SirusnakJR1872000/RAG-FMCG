# Evaluation: hybrid-e5-small-v2+rerank-ms-marco-MiniLM-L-6-v2 (dev)

Git commit `15a499f` · 18 answerable questions (one question = 5.6 points)

| Retriever | Embedding model | Reranker | Hit@1 | Hit@5 | MRR@10 | retrieval p50 ms | rerank p50 / p90 ms |
|---|---|---|---|---|---|---|---|
| hybrid | e5-small-v2 | ms-marco-MiniLM-L-6-v2 | 0.94 | 0.94 | 0.95 | 18 | 787 / 860 |

## Questions not hit in the top 5

- G-010 Does Acme's OOS SOP align with ICH Q7 on investigating out-of-specification results? → top: ACME-SOP-QC-007 §8, ACME-SOP-QA-005 §2, ACME-SOP-QC-007 §1
