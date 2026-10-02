"""Shared loading for the retrieval-options offline steps (no Atlas imports: run in a scratch
environment with torch + sentence-transformers, outside the repo's dependencies).

Inputs are the files `retrieval_options_collect.py` wrote (memories.json = every fact of the
throwaway bank, answers.json = the known answers resolved against it, documents.json) plus the
repo's probe set and known answers.
"""

import json
import re
from pathlib import Path

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[2]
EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
WEB_INSTRUCTION = "Given a web search query, retrieve relevant passages that answer the query"
TASK_INSTRUCTION = (
    "Given a research question about the optical and AI-infrastructure supply chain, "
    "retrieve passages from company filings that answer it"
)


def load(run: Path):
    memories = json.loads((run / "memories.json").read_text(encoding="utf-8"))
    answers = json.loads((run / "answers.json").read_text(encoding="utf-8"))["resolved"]
    probes = yaml.safe_load((REPO / "configs/memory/probes.yaml").read_text(encoding="utf-8"))
    known = yaml.safe_load((REPO / "configs/memory/known-answers.yaml").read_text(encoding="utf-8"))
    sentences = {a["id"]: a["sentence"] for a in known["answers"]}
    return memories, answers, probes["probes"], sentences


def section_key(document_id: str | None) -> str | None:
    """'srcv:<version>:<anchor>' -> '<version>:<anchor>' (the bank's document is one section)."""
    if not document_id or not document_id.startswith("srcv:"):
        return None
    return document_id[5:]


def answer_key(answer: dict) -> str:
    return f"{answer['source_version_id']}:{answer['section']}"


def queries(probes) -> list[dict]:
    out = []
    for probe in probes:
        for i, text in enumerate((probe["question"].strip(), *probe["queries"])):
            out.append({"probe": probe["id"], "query": " ".join(text.split()), "is_question": i == 0})
    return out


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:[.\-/][a-z0-9]+)*", text.lower())


def bm25_scores(query: str, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> np.ndarray:
    n = len(docs)
    avg = sum(len(d) for d in docs) / n
    df: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    scores = np.zeros(n)
    for t in set(tokens(query)):
        if t not in df:
            continue
        idf = np.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
        for i, d in enumerate(docs):
            f = d.count(t)
            if f:
                scores[i] += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(d) / avg))
    return scores
