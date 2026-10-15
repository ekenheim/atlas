# 13: Bulk retention off

Type: task
Status: done
Blocked by: 12

## Question

Once the conclusions bank is live and a session has recalled a judged Belief from it: a home-ops PR setting `ATLAS_BULK_RETENTION=off` on the Atlas Deployment (the owner merges); health reports it; the nightly ingest keeps the archive current while the research bank stops growing. Record the day and the bank's final counts in the log; the research bank's retirement is a later decision.

## Answer

2026-10-15: home-ops-upgrade #7587 merged by the owner; production (0.6.2) reports `bulk_retention: off` from 08:32 UTC. Preconditions met that morning: the conclusions bank `atlas-beliefs` live (template 1.0.0, the 2 judged Beliefs moved, `in_research_bank` 0) and a theme-scoped recall with `bank: beliefs` returned 7 memories, all provenance `belief`. The research bank's final counts (`atlas-ai-infrastructure`): 3,570 sections (1,703 completed, 55 zero-fact, 1,812 retired; 0 pending, failed or stuck), 45,276 facts; 1,196 parsed English versions (522 in Memory, 443 retired, 231 all skipped, 0 not submitted); that day's reconciliation clean; the last consolidation completed with 0 pending. Its retirement is a later decision.
