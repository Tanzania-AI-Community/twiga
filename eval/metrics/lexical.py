from typing import Any

from nltk.translate.bleu_score import SmoothingFunction, sentence_bleu
from rouge_score import rouge_scorer

from eval.metrics.base import Metric

_ROUGE_TYPES = ["rouge1", "rouge2", "rougeL"]


class LexicalMetrics(Metric):
    name = "lexical"
    required_columns = ["user_query", "reference"]

    def __init__(self) -> None:
        self._scorer = rouge_scorer.RougeScorer(_ROUGE_TYPES, use_stemmer=False)
        self._smooth = SmoothingFunction().method1

    def _reference_columns(self, row: dict[str, Any]) -> list[str]:
        """Return all non-empty reference column values from a row."""
        refs = []
        for k, v in row.items():
            if k.startswith("reference") and isinstance(v, str) and v.strip():
                refs.append(v.strip())
        return refs or [row.get("reference", "")]

    async def ascore(self, row: dict[str, Any]) -> dict:
        hypothesis = str(row.get("response", "")).strip()
        references = self._reference_columns(row)

        best: dict[str, float] = {
            "rouge_1": 0.0,
            "rouge_2": 0.0,
            "rouge_l": 0.0,
            "bleu": 0.0,
        }

        for ref in references:
            if not ref:
                continue
            scores = self._scorer.score(ref, hypothesis)
            best["rouge_1"] = max(best["rouge_1"], scores["rouge1"].fmeasure)
            best["rouge_2"] = max(best["rouge_2"], scores["rouge2"].fmeasure)
            best["rouge_l"] = max(best["rouge_l"], scores["rougeL"].fmeasure)

            ref_tokens = ref.split()
            hyp_tokens = hypothesis.split()
            if ref_tokens and hyp_tokens:
                bleu = sentence_bleu(
                    [ref_tokens],
                    hyp_tokens,
                    smoothing_function=self._smooth,
                )
                best["bleu"] = max(best["bleu"], bleu)

        return best
