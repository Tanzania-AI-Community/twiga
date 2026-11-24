"""
Write review.md for a person to spot-check the LLM labels.

For each query it lists the grade-2 chunks, plus vector top-5 chunks the judge
graded 1 (the borderline cases that move the metrics most). Record corrections in
label_overrides.jsonl as {"id": "q03", "chunk": 30, "grade": 1}; evaluate.py applies them.

Run from the twiga/ directory (needs chunks.json):
python3 scripts/eval/search_knowledge/review_sheet.py
"""

import json
from pathlib import Path

HERE = Path(__file__).parent
PREVIEW_CHARS = 300


def main():
    chunks = json.load(open(HERE / "chunks.json"))
    lines = ["# Label review", ""]
    for line in open(HERE / "labels.jsonl"):
        q = json.loads(line)
        labels = q["labels"]
        grade2 = [i for i, g in labels.items() if g == 2]
        borderline = [
            str(i) for i in q["vector_ranking"][:5] if labels.get(str(i)) == 1
        ]
        lines += [f"## {q['id']} ({q['topic']}): {q['query']}", ""]
        for title, ids in (("Grade 2", grade2), ("Top 5 graded 1", borderline)):
            if not ids:
                continue
            lines.append(f"**{title}**")
            for i in ids:
                text = " ".join(chunks[i].split())[:PREVIEW_CHARS]
                lines.append(f"- `{i}` {text}")
            lines.append("")
        if not grade2:
            lines += ["_No grade-2 chunks._", ""]
    (HERE / "review.md").write_text("\n".join(lines))
    print(f"Wrote {HERE / 'review.md'}")


if __name__ == "__main__":
    main()
