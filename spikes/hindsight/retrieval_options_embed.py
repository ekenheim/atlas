"""Retrieval options, step 2: the embedding query instruction, measured with the local weights
of today's `Qwen3-Embedding-0.6B` (1,024 dimensions) over every fact of the throwaway bank.

For each of the 25 recalls' queries, the cosine rank of the known answers' facts among all
facts, with the query as the server sends it today (no prefix), with Qwen3's documented
web-search instruction, and with a task-specific instruction. Also writes the embeddings and the
answer facts the reranker step uses.

    <scratch python> retrieval_options_embed.py RUN_DIR
"""

import json
import sys
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

import retrieval_options_common as c

run = Path(sys.argv[1])
memories, answers, probes, sentences = c.load(run)
model = SentenceTransformer(c.EMBEDDING_MODEL, device="cpu", model_kwargs={"torch_dtype": "float32"})
texts = [m["text"] for m in memories]
fact_emb = model.encode(texts, batch_size=16, normalize_embeddings=True, show_progress_bar=False)
np.save(run / "fact-embeddings.npy", fact_emb)

# Answer facts: the facts of the answer's section that most resemble its sentence (the bank
# keeps no span for a fact, so this is an approximation: top 2 by cosine to the sentence, and
# at least 0.6).
sent_emb = {
    a["id"]: model.encode(sentences[a["id"]], normalize_embeddings=True) for a in answers
}
keys = [c.section_key(m["document_id"]) for m in memories]
answer_facts: dict[str, list[dict]] = {}
for a in answers:
    idx = [i for i, k in enumerate(keys) if k == c.answer_key(a)]
    sims = sorted(((float(fact_emb[i] @ sent_emb[a["id"]]), i) for i in idx), reverse=True)
    answer_facts[a["id"]] = [
        {"index": i, "sim": round(s, 3), "text": texts[i]} for s, i in sims[:2] if s >= 0.6
    ]
    print(a["id"], "section facts:", len(idx), "answer facts:", [f["sim"] for f in answer_facts[a["id"]]])
(run / "answer-facts.json").write_text(json.dumps(answer_facts, indent=1), encoding="utf-8")

qs = c.queries(probes)
variants = {
    "none (today)": lambda q: q,
    "web-search instruction": lambda q: f"Instruct: {c.WEB_INSTRUCTION}\nQuery:{q}",
    "task instruction": lambda q: f"Instruct: {c.TASK_INSTRUCTION}\nQuery:{q}",
}
rows = []  # one per (variant, query, answer)
for name, fmt in variants.items():
    q_emb = model.encode([fmt(q["query"]) for q in qs], normalize_embeddings=True)
    for qi, q in enumerate(qs):
        sims = fact_emb @ q_emb[qi]
        order = np.argsort(-sims)
        rank_of = np.empty(len(order), dtype=int)
        rank_of[order] = np.arange(1, len(order) + 1)
        for a in answers:
            if a["question"] != q["probe"] or not answer_facts[a["id"]]:
                continue
            fact_ranks = [int(rank_of[f["index"]]) for f in answer_facts[a["id"]]]
            sec_idx = [i for i, k in enumerate(keys) if k == c.answer_key(a)]
            rows.append(
                {
                    "variant": name,
                    "query_index": qi,
                    "probe": q["probe"],
                    "is_question": q["is_question"],
                    "answer": a["id"],
                    "fact_rank": min(fact_ranks),
                    "fact_cosine": float(max(sims[f["index"]] for f in answer_facts[a["id"]])),
                    "section_first_rank": int(min(rank_of[i] for i in sec_idx)),
                }
            )
(run / "embedding-instruction-rows.json").write_text(json.dumps(rows), encoding="utf-8")

print("\nvariant | pairs | median fact rank | fact@10 | fact@45 | median best cosine | section-first@10")
for name in variants:
    r = [x for x in rows if x["variant"] == name]
    fr = np.array([x["fact_rank"] for x in r])
    print(
        f"{name} | {len(r)} | {np.median(fr):.0f} | {(fr <= 10).mean():.3f} | {(fr <= 45).mean():.3f}"
        f" | {np.median([x['fact_cosine'] for x in r]):.3f}"
        f" | {(np.array([x['section_first_rank'] for x in r]) <= 10).mean():.3f}"
    )
