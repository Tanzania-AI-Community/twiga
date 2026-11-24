"""
Sweep cosine-distance cutoffs on today's vector search (top 15).

Chunks farther than the cutoff are dropped, so results can be fewer than 15 or empty.
Needs distances.jsonl from measure_search.py. Grade 2 counts as relevant.

Run from the twiga/ directory:
python3 scripts/eval/search_knowledge/cutoff_sweep.py
"""

import statistics
from pathlib import Path

from evaluate import load, load_questions

HERE = Path(__file__).parent
TOP_K = 15
CUTOFFS = [None, 0.30, 0.31, 0.32, 0.33, 0.34, 0.35]


def main():
    questions = {q["id"]: q for q in load_questions()}
    distances = {d["id"]: d for d in load(HERE / "distances.jsonl")}
    print(
        "cutoff | avg chunks | precision | recall | in-scope empty | out-of-scope empty"
    )
    for cutoff in CUTOFFS:
        counts, precision, recall = [], [], []
        in_scope_empty = out_of_scope_empty = 0
        for qid, d in distances.items():
            kept = [
                cid
                for cid, dist in zip(d["ranking"][:TOP_K], d["distances"][:TOP_K])
                if cutoff is None or dist <= cutoff
            ]
            labels = questions[qid]["labels"]
            if questions[qid]["topic"] == "oos":
                out_of_scope_empty += not kept
                continue
            in_scope_empty += not kept
            counts.append(len(kept))
            hits = sum(labels.get(str(cid), 0) == 2 for cid in kept)
            recall.append(hits / sum(g == 2 for g in labels.values()))
            if kept:
                precision.append(hits / len(kept))
        n_out = sum(q["topic"] == "oos" for q in questions.values())
        print(
            f"{str(cutoff):6} | {statistics.mean(counts):10.1f} | "
            f"{statistics.mean(precision):9.2f} | {statistics.mean(recall):6.2f} | "
            f"{in_scope_empty}/{len(counts)} | {out_of_scope_empty}/{n_out}"
        )


if __name__ == "__main__":
    main()
