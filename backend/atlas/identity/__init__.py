"""Entity resolution: companies → legal entities, LEIs, CIKs and listings (build plan §7.1).

`EntityResolver.resolve` is the deterministic pipeline over SEC, GLEIF and OpenFIGI;
`resolve_mention` looks in the universe first (the entry point for Candidates from leads);
`resolve_universe` resolves the configured companies and stores what it proposes;
`IdentityMappings` is the owner's review queue.
"""

from atlas.identity.http import IdentitySourceError
from atlas.identity.resolver import (
    Alias,
    Entity,
    EntityResolver,
    Fact,
    Listing,
    Mention,
    Proposal,
    Resolution,
)

__all__ = [
    "Alias",
    "Entity",
    "EntityResolver",
    "Fact",
    "IdentitySourceError",
    "Listing",
    "Mention",
    "Proposal",
    "Resolution",
]
