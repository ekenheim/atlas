"""Discovery (spec Phase 3, "Discovery"): the Scout's SearXNG queries and the Tier C leads
they find.

`searxng` is the SearXNG client; `service` runs a discovery (the Scout role call, the
searches, the leads) and reads discoveries back; `leads` holds the canonical URL rule, lead
storage and the lead read side; `handlers` registers the `discover` job.
"""

from atlas.discovery.handlers import register_discovery_handlers
from atlas.discovery.leads import Lead, canonical_url, list_leads
from atlas.discovery.searxng import (
    SearchFailed,
    SearchResponse,
    SearchResult,
    SearXNGClient,
    UnresponsiveEngine,
)
from atlas.discovery.service import (
    DISCOVER_KIND,
    DiscoverPayload,
    Discovery,
    DiscoveryFailed,
    DiscoveryQuery,
    Scout,
    get_discovery,
    list_discoveries,
)

__all__ = [
    "DISCOVER_KIND",
    "DiscoverPayload",
    "Discovery",
    "DiscoveryFailed",
    "DiscoveryQuery",
    "Lead",
    "Scout",
    "SearXNGClient",
    "SearchFailed",
    "SearchResponse",
    "SearchResult",
    "UnresponsiveEngine",
    "canonical_url",
    "get_discovery",
    "list_discoveries",
    "list_leads",
    "register_discovery_handlers",
]
