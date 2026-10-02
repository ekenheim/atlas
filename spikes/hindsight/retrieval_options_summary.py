"""Retrieval options, step 4: extra summary statistics (MRR, paired changes) over the results."""

import json
import sys
from pathlib import Path

import numpy as np

run = Path(sys.argv[1])
r = json.loads((run / "rerank-results.json").read_text())
for n, v in r["rerankers"].items():
    br = [a["best_fact_rank"] for a in v["per_answer"]]
    print(n, "MRR", round(float(np.mean([1 / x for x in br])), 3), "ranks", sorted(br))
rows = json.loads((run / "embedding-instruction-rows.json").read_text())
base = {(a["query_index"], a["answer"]): a["fact_rank"] for a in rows if a["variant"] == "none (today)"}
for var in ["none (today)", "web-search instruction", "task instruction"]:
    mine = [a for a in rows if a["variant"] == var]
    x = np.array([a["fact_rank"] for a in mine])
    better = sum(a["fact_rank"] < base[(a["query_index"], a["answer"])] for a in mine)
    worse = sum(a["fact_rank"] > base[(a["query_index"], a["answer"])] for a in mine)
    print(var, "MRR", round(float((1 / x).mean()), 3), "p25/50/75", np.percentile(x, [25, 50, 75]),
          "better", better, "worse", worse)
