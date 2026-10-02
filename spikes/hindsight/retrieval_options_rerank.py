"""Retrieval options, step 3: rerankers compared offline on the same candidate pools.

The pool of each of the 25 recalls (a probe question and its four queries) is rebuilt offline from
the throwaway bank's 407 facts (the live pool was lost, see the note): a semantic arm (today's
Qwen3-Embedding-0.6B weights, the query sent as the server sends it, no prefix) and a keyword arm
(BM25), each 200 deep, fused by RRF (k=60) and cut to 300 (Hindsight's reranker cap). The graph
and temporal arms are not rebuilt. Then each reranker orders that pool:

  rrf         the fused order, no reranker (Hindsight's passthrough)
  minilm      cross-encoder/ms-marco-MiniLM-L-6-v2 (what the cluster's TEI sidecar serves)
  bge-m3      BAAI/bge-reranker-v2-m3
  qwen3-0.6b  Qwen/Qwen3-Reranker-0.6B (the model card's yes/no prompt)

    <scratch python> retrieval_options_rerank.py RUN_DIR [--only minilm,bge-m3,...]
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import CrossEncoder, SentenceTransformer
from transformers import AutoModelForCausalLM, AutoTokenizer

import retrieval_options_common as c

run = Path(sys.argv[1])
only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
memories, answers, probes, _ = c.load(run)
texts = [m["text"] for m in memories]
keys = [c.section_key(m["document_id"]) for m in memories]
fact_emb = np.load(run / "fact-embeddings.npy")
answer_facts = json.loads((run / "answer-facts.json").read_text(encoding="utf-8"))
qs = c.queries(probes)

# --- pools ---------------------------------------------------------------------------------
embedder = SentenceTransformer(c.EMBEDDING_MODEL, device="cpu", model_kwargs={"torch_dtype": "float32"})
doc_tokens = [c.tokens(t) for t in texts]
pools: list[list[int]] = []
for q in qs:
    sem = fact_emb @ embedder.encode(q["query"], normalize_embeddings=True)
    sem_rank = list(np.argsort(-sem)[:200])
    kw = c.bm25_scores(q["query"], doc_tokens)
    kw_rank = [int(i) for i in np.argsort(-kw)[:200] if kw[i] > 0]
    fused: dict[int, float] = {}
    for rank_list in (sem_rank, kw_rank):
        for r, i in enumerate(rank_list, start=1):
            fused[int(i)] = fused.get(int(i), 0.0) + 1.0 / (60 + r)
    pools.append([i for i, _ in sorted(fused.items(), key=lambda kv: -kv[1])][:300])
del embedder
print("pool sizes", min(map(len, pools)), max(map(len, pools)), flush=True)

# --- rerankers -----------------------------------------------------------------------------


def minilm():
    m = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", device="cpu", max_length=512)
    return lambda q, docs: m.predict([(q, d) for d in docs], batch_size=32, show_progress_bar=False)


def bge():
    m = CrossEncoder("BAAI/bge-reranker-v2-m3", device="cpu", max_length=512)
    return lambda q, docs: m.predict([(q, d) for d in docs], batch_size=16, show_progress_bar=False)


def qwen():
    tok = AutoTokenizer.from_pretrained("Qwen/Qwen3-Reranker-0.6B", padding_side="left")
    model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen3-Reranker-0.6B", torch_dtype=torch.float32).eval()
    yes, no = tok.convert_tokens_to_ids("yes"), tok.convert_tokens_to_ids("no")
    prefix = (
        "<|im_start|>system\nJudge whether the Document meets the requirements based on the Query "
        'and the Instruct provided. Note that the answer can only be "yes" or "no".'
        "<|im_end|>\n<|im_start|>user\n"
    )
    suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    instruction = "Given a web search query, retrieve relevant passages that answer the query"

    def score(q, docs):
        out: list[float] = [0.0] * len(docs)
        order = sorted(range(len(docs)), key=lambda i: len(docs[i]))  # less padding
        for s in range(0, len(docs), 16):
            ids = order[s : s + 16]
            batch = [
                f"{prefix}<Instruct>: {instruction}\n<Query>: {q}\n<Document>: {docs[i]}{suffix}"
                for i in ids
            ]
            enc = tok(batch, padding=True, truncation=True, max_length=768, return_tensors="pt")
            with torch.no_grad():
                logits = model(**enc).logits[:, -1, :]
            pair = torch.stack([logits[:, no], logits[:, yes]], dim=1)
            for i, v in zip(ids, torch.log_softmax(pair, dim=1)[:, 1].exp().tolist()):
                out[i] = v
        return out

    return score


FACTORIES = {"minilm": minilm, "bge-m3": bge, "qwen3-0.6b": qwen}
scores_path = run / "rerank-scores.json"
store: dict = json.loads(scores_path.read_text()) if scores_path.exists() else {}
for name, factory in FACTORIES.items():
    if only and name not in only:
        continue
    if name in store and len(store[name]["scores"]) == len(qs):
        continue
    score = factory()
    store[name] = {"scores": [], "wall": [], "cpu": [], "pairs": []}
    for qi, q in enumerate(qs):
        docs = [texts[i] for i in pools[qi]]
        t0, p0 = time.perf_counter(), time.process_time()
        s = [float(x) for x in score(q["query"], docs)]
        store[name]["scores"].append(s)
        store[name]["wall"].append(time.perf_counter() - t0)
        store[name]["cpu"].append(time.process_time() - p0)
        store[name]["pairs"].append(len(docs))
        print(name, qi, f"{store[name]['wall'][-1]:.1f}s", flush=True)
        scores_path.write_text(json.dumps(store), encoding="utf-8")
    del score

# --- metrics -------------------------------------------------------------------------------


def orders(name: str, qi: int) -> list[int]:
    if name == "rrf":
        return pools[qi]
    s = store[name]["scores"][qi]
    return [pools[qi][j] for j in np.argsort(-np.array(s), kind="stable")]


def first_rank(order: list[int], pred) -> int | None:
    for r, i in enumerate(order, start=1):
        if pred(i):
            return r
    return None


names = ["rrf", *[n for n in FACTORIES if n in store]]
result: dict = {"pool_sizes": [len(p) for p in pools], "rerankers": {}}
by_probe: dict[str, list[int]] = {}
for qi, q in enumerate(qs):
    by_probe.setdefault(q["probe"], []).append(qi)

for name in names:
    per_answer = []
    for a in answers:
        if not answer_facts[a["id"]]:
            continue
        key = c.answer_key(a)
        afacts = {f["index"] for f in answer_facts[a["id"]]}
        sec_ranks, fact_ranks, lists = [], [], []
        for qi in by_probe[a["question"]]:
            o = orders(name, qi)
            sec_ranks.append(first_rank(o, lambda i: keys[i] == key))
            fact_ranks.append(first_rank(o, lambda i: i in afacts))
            seen: list[str] = []
            for i in o:
                if keys[i] and keys[i] not in seen:
                    seen.append(keys[i])
            lists.append(seen)
        merged: list[str] = []
        for r in range(max(map(len, lists))):
            for lst in lists:
                if r < len(lst) and lst[r] not in merged:
                    merged.append(lst[r])
        per_answer.append(
            {
                "answer": a["id"],
                "question": a["question"],
                "section_rank_per_recall": sec_ranks,
                "fact_rank_per_recall": fact_ranks,
                "best_section_rank": min((r for r in sec_ranks if r), default=None),
                "best_fact_rank": min((r for r in fact_ranks if r), default=None),
                "merged_section_rank": merged.index(key) + 1 if key in merged else None,
            }
        )

    def rate(rows, field, k):
        return round(sum(1 for r in rows if r[field] and r[field] <= k) / len(rows), 3)

    def summarise(rows):
        return {
            "answers": len(rows),
            "section_best@10": rate(rows, "best_section_rank", 10),
            "section_best@45": rate(rows, "best_section_rank", 45),
            "fact_best@10": rate(rows, "best_fact_rank", 10),
            "fact_best@45": rate(rows, "best_fact_rank", 45),
            "merged_section@10": rate(rows, "merged_section_rank", 10),
            "merged_section@50": rate(rows, "merged_section_rank", 50),
            "median_best_fact_rank": float(np.median([r["best_fact_rank"] or 999 for r in rows])),
        }

    result["rerankers"][name] = {
        "pooled": summarise(per_answer),
        "by_question": {
            p: summarise([r for r in per_answer if r["question"] == p]) for p in by_probe
        },
        "per_answer": per_answer,
        "wall_s_per_query": float(np.mean(store[name]["wall"])) if name in store else 0.0,
        "cpu_s_per_query": float(np.mean(store[name]["cpu"])) if name in store else 0.0,
        "pairs_per_query": float(np.mean(store[name]["pairs"])) if name in store else 0.0,
    }
(run / "rerank-results.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
for name in names:
    r = result["rerankers"][name]
    print(name, r["pooled"], f"wall {r['wall_s_per_query']:.2f}s cpu {r['cpu_s_per_query']:.2f}s")

