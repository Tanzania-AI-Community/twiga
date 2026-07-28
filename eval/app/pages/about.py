"""About / How to read results — in-app documentation.

Explains what each suite tests and, crucially, how to interpret the numbers a
run produces.
"""

import streamlit as st


def render():
    st.title("About Twiga Evals")
    st.caption(
        "What this tool tests, how it scores Twiga, and — most importantly — how "
        "to read the results."
    )

    # ── What it tests ───────────────────────────────────────────────────────────
    st.header("What it tests")
    st.markdown(
        "Twiga is a WhatsApp assistant that answers Tanzanian teachers **only from "
        "the curriculum textbooks**. The core risk is that it answers fluently but "
        "wrongly — inventing facts the book never states. Everything here exists to "
        "catch that. **Generation** and **Abstention** score Twiga's *real* pipeline "
        "(live retrieval + its actual system prompt and temperature). **Retrieval**'s "
        "search is real too, but the answer its judge metrics score over that context "
        "comes from a plain generic prompt, not Twiga's own. A **full evaluation** "
        "always runs all four suites:"
    )
    st.markdown(
        "- **📝 Generation** — Twiga answers every curriculum question from all four "
        "subjects. Every fact in the reply is checked against the textbook passages "
        "it retrieved.\n"
        "- **🔤 Lexical** — ROUGE/BLEU word-overlap of those answers vs. the reference "
        "answers. A rough sanity check; the grounding metrics matter far more.\n"
        "- **🔍 Retrieval** — does search surface the *right* textbook pages? The same "
        "questions are asked in four phrasings — plain, keyword, misspelled, Swahili — "
        "so a gap between styles can only come from the phrasing.\n"
        "- **🚫 Abstention** — on questions the textbook *can't* answer, does Twiga "
        "decline instead of making something up?"
    )
    st.markdown(
        "A **⚡ quick run** is the cheap smoke test between full evaluations: "
        "faithfulness on a fixed 100-question sample, the abstention set, and "
        "judge-free Recall@10. Quick runs get their own section on the Overview and "
        "never move the headline numbers."
    )
    st.markdown(
        "Grading is done by an **LLM judge**, fixed on purpose: different judges give "
        "different scores, so keeping it constant is what lets you compare runs over "
        "time. How Twiga itself is run (model, temperature, retrieved-chunk count) "
        "mirrors production automatically — those settings are imported from Twiga, "
        "not configurable in the eval, so the two can't drift apart."
    )

    # ── How to read the results ─────────────────────────────────────────────────
    st.header("How to read the results")

    st.subheader("The four headline numbers")
    st.markdown(
        "These are on the **Overview** tab, taken from your latest full evaluation "
        "(quick runs never move them). Higher is better for all four. As rough "
        "guidance, treat **> 90%** as strong, **75–90%** as watch-it, and **< 75%** "
        "as a problem worth digging into on the Runs tab."
    )
    st.table({
        "Metric": [
            "Answers backed by the book",
            "Citations that hold up",
            "Declines when it should",
            "Finds the right pages",
        ],
        "Means": [
            "Share of individual facts in Twiga's answers that the retrieved textbook supports.",
            "When Twiga cites a chunk, how often that chunk really supports the point.",
            "On unanswerable questions, how often Twiga refuses instead of inventing.",
            "How often search puts a correct chunk in its top 10 (Recall@10).",
        ],
        "If it's low…": [
            "Twiga is stating facts the book doesn't back — see the claim breakdown.",
            "Twiga cites the wrong sources — misleading even when the fact is right.",
            "Twiga bluffs on things it shouldn't answer; hallucination risk is highest here.",
            "Retrieval is the bottleneck — the model never sees the right pages.",
        ],
    })

    st.subheader("On full runs, unsupported facts get split further")
    st.markdown(
        "On the **Claims** tab of a **full** run, each unsupported fact is also "
        "labelled by cause — this is how a low grounding score gets explained rather "
        "than just reported. **Quick runs skip this extra check**, so their Claims tab "
        "only shows grounded / contradicted / unverifiable, without the split below. "
        "(A claim the check itself fails on is left unlabelled.)"
    )
    st.markdown(
        "- ✅ **Grounded** — supported by a passage Twiga retrieved. Good.\n"
        "- 📖 **In the book, not retrieved** — the fact *is* in the textbook, but "
        "search didn't surface it. This is a **retrieval** problem (chunking, "
        "embeddings, top-k) — the model actually did fine.\n"
        "- 🚫 **Not in the book** — the fact appears nowhere in the textbook. This is "
        "a **true hallucination** — a prompt/model problem."
    )
    st.info(
        "This split matters: a 📖 and a 🚫 look identical in a bare faithfulness "
        "score, but they point to completely different fixes."
    )

    st.subheader("Faithfulness vs. claim grounding")
    st.markdown(
        "**Faithfulness** is the judge's overall score for an answer. "
        "**Claim grounding** is the fraction of individual facts that check out. "
        "They usually move together; when they diverge, trust the claim-level view — "
        "it's the one that tells you *which* facts failed and why. An 'unverifiable' "
        "fact counts against the score (we don't give the benefit of the doubt), and "
        "gets a second-opinion judge before the final tally."
    )

    st.subheader("Reading abstention")
    st.markdown(
        "The abstention set is split into **out-of-domain** (wrong subject), "
        "**not-in-book** (too specific/recent), and **false-premise** (the question "
        "embeds a wrong fact). A response passes if it **declines** or **corrects the "
        "premise**; it fails if it **answers** as though the book supported it. "
        "The three categories don't always fail the same way — check the per-category "
        "table to see which one is weakest in this run."
    )

    st.subheader("Retrieval by query style")
    st.markdown(
        "The Retrieval suite asks the **same questions four ways** — plain, keyword, "
        "misspelled, Swahili — sharing the same golden chunks, so a gap between styles "
        "is caused by the phrasing alone. A big drop on *keyword / misspelled / "
        "Swahili* means retrieval is fragile to how a real teacher actually types — "
        "often the most actionable finding in a run. The full breakdown (per style, "
        "per chapter, missed queries) is on each run's **Retrieval** tab."
    )

    # ── Comparing runs ──────────────────────────────────────────────────────────
    st.header("Comparing runs")
    st.markdown(
        "The point of saving runs is to see whether a change to Twiga helped. On the "
        "**Runs** tab, open a run and use **Compare with…** to see per-metric deltas "
        "and exactly which questions regressed. Two cautions:"
    )
    st.markdown(
        "- **The judge is fixed**, so runs are comparable by default. What you change "
        "between runs is Twiga itself (its prompt, model, or retrieval) — and those "
        "settings are mirrored from production, shown on the Run evaluation tab.\n"
        "- **Small deltas are noise.** LLM judges aren't perfectly deterministic — and "
        "Twiga answers at its real temperature, not zero — so treat movements under a "
        "few points as flat, and look at *which* questions changed, not just the average."
    )

    st.caption(
        "For the full workflow and internals, see `eval/` in the repository."
    )
