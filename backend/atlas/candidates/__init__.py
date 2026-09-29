"""Candidates (spec §8.3; "Discovery"): companies outside the universe that leads name.

`proposals` runs the `propose_candidates` job (the mention extractor role over a
discovery's leads, entity resolution of each mention, a Candidate per unseeded match);
`service` reads Candidates and holds the owner's commit (the company joins the universe in
the database and its ingest is enqueued) and reject (kept, with its reason); `handlers`
registers the job.
"""

from atlas.candidates.handlers import register_candidate_handlers
from atlas.candidates.proposals import (
    PROPOSE_CANDIDATES_KIND,
    CandidateProposer,
    ProposePayload,
    exchange_mic,
)
from atlas.candidates.service import (
    CANDIDATE_STATES,
    Candidate,
    CandidateCommit,
    CandidateDecided,
    CandidateLead,
    CandidateRefused,
    CandidateReject,
    Candidates,
    CandidateState,
    get_candidate,
    list_candidates,
)

__all__ = [
    "CANDIDATE_STATES",
    "PROPOSE_CANDIDATES_KIND",
    "Candidate",
    "CandidateCommit",
    "CandidateDecided",
    "CandidateLead",
    "CandidateProposer",
    "CandidateRefused",
    "CandidateReject",
    "CandidateState",
    "Candidates",
    "ProposePayload",
    "exchange_mic",
    "get_candidate",
    "list_candidates",
    "register_candidate_handlers",
]
