# search_knowledge retrieval eval

Small eval set for the `search_knowledge` baseline (issue #325), built from the local seed book
*Geography for Secondary Schools Student's Book Form Two*.

## Files

- `questions.jsonl`: 54 search phrases across the 9 chapters, plus 5 out-of-scope ones (`topic: oos`).
- `labels.jsonl`: for each query, the vector top 50 and a grade for every pooled chunk from the first judge (MiniMax-M3): 2 = answers it, 1 = partly relevant, 0 = not.
- `labels_judge2.jsonl`: the same chunks regraded by a second judge (DeepSeek-V4.1-Flash), in shuffled order.
- `label_overrides.jsonl`: tiebreak decisions where the two judges disagreed on grade 2. Each line records who decided (`"by"`).
- `distances.jsonl`: vector top 50 chunk ids with their cosine distances, used by the cutoff sweep.

Scripts:

- `build_labels.py`: pools the vector top 50 and keyword top 20 chunks per query and asks the first judge to grade them. It resumes if interrupted.
- `second_judge.py`: regrades with the second judge and writes `disagreements.md`.
- `review_sheet.py`: writes `review.md` for a person to spot-check labels.
- `measure_search.py`: records distances and per-step search latency.
- `evaluate.py`: scores vector order, optionally against a local reranker. Overrides are applied.
- `cutoff_sweep.py`: scores vector search with a maximum cosine distance.

## Run

```bash
# 1. Labels (in the app container; needs Google ADC and LLM_API_KEY). Only needed after changing questions or chunks.
docker exec -w /app -e PYTHONPATH=/app dev-app-1 uv run python scripts/eval/search_knowledge/build_labels.py
docker exec -w /app -e PYTHONPATH=/app:/app/scripts/eval/search_knowledge dev-app-1 uv run python scripts/eval/search_knowledge/second_judge.py
docker exec -w /app -e PYTHONPATH=/app dev-app-1 uv run python scripts/eval/search_knowledge/measure_search.py

# 2. Export chunk texts (git-ignored: textbook content)
docker exec dev-db-1 psql -U postgres -d twiga_db -At \
  -c "select json_object_agg(id, content) from chunks where chunk_type='text'" \
  > scripts/eval/search_knowledge/chunks.json

# 3. Score
python3 scripts/eval/search_knowledge/evaluate.py none --k 5 8 10 15
python3 scripts/eval/search_knowledge/cutoff_sweep.py
```

## Label quality

- The two judges gave the same grade on 85% of the pooled chunks.
- They disagreed on whether a chunk answers the query (grade 2) for 106 chunks. Those were resolved by a third LLM (Claude), not by a person: it sided with the first judge 62 times and the second 44 times.
- The ~260 chunks both judges graded 2 were not reviewed.
- The conclusions below hold under either judge's labels alone.

## Results (2026-11-20, 54 in-scope queries, final labels)

### Current search vs. a local reranker

| Setup | P@5 | P@15 | Recall@15 | MRR | nDCG@15 | Added latency p50 / p95 |
|---|---|---|---|---|---|---|
| Vector search (today) | 0.67 | 0.33 | 0.93 | 1.00 | 0.88 | – |
| + bge-reranker-v2-m3, pool 30 | 0.62 | 0.32 | 0.91 | 0.94 | 0.84 | 0.75s / 0.85s (Mac CPU) |
| + bge-reranker-v2-m3, pool 50 | 0.62 | 0.31 | 0.89 | 0.94 | 0.83 | 1.23s / 2.34s (Mac CPU) |

Reranking did not beat vector order. The median query has about 5 grade-2 chunks, so P@15 cannot go much above 0.33 however the 15 are ordered.
Reranking is parked on `feat/search-knowledge-reranking`.

### Distance cutoff on vector top 15

Chunks with cosine distance above the cutoff are dropped.

| Cutoff | Avg chunks | Precision | Recall | In-scope queries with 0 results | Out-of-scope queries with 0 results |
|---|---|---|---|---|---|
| none (today) | 15.0 | 0.33 | 0.93 | 0/54 | 0/5 |
| 0.32 | 7.2 | 0.65 | 0.80 | 0/54 | 5/5 |
| 0.33 | 8.7 | 0.57 | 0.84 | 0/54 | 5/5 |
| 0.34 | 9.8 | 0.51 | 0.87 | 0/54 | 5/5 |
| 0.35 | 11.0 | 0.46 | 0.88 | 0/54 | 5/5 |

Every in-scope query's best match was at distance ≤ 0.306, and every out-of-scope query's best match was ≥ 0.352.

### Search latency (warm, per query)

| Step | p50 | p95 |
|---|---|---|
| Query embedding (Vertex AI) | 0.33s | 0.94s |
| pgvector query, top 50 | 0.004s | 0.005s |

The first call after startup took 1.1s. Reusing the embedding client instead of creating one per query saved about 0.01s, so it is not worth changing.

## Caveats

- The cutoff was tuned and measured on the same 59 queries, so it may be optimistic. It also depends on the embedding model (`gemini-embedding-001`) and must be retuned if that changes.
- Only 5 out-of-scope queries were tested.
- The queries were written from the book's headings, so they are cleaner than real teacher queries.
- One English book only. Production classes may have several resources and Swahili content.
