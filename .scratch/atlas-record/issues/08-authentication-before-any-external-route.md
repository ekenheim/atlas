# Authentication before any external route

Type: task
Status: wontfix
Blocked by: 03, and needed only if the drop box fails and the owner chooses an external import route

## Why

Atlas's API and MCP have no authentication of their own. That is acceptable while the only route is `envoy-internal`.

If the owner opens an external route (ticket 03's fallback), the import endpoint needs a bearer token before the route exists:
- the token lives in a Secret;
- it is compared in constant time;
- every other route stays internal-only.

## Done when

- [ ] Either the ticket is not needed because the drop box works, or the token is in place and an unauthenticated import is refused with 401.

## Comments

- 2026-10-24, lead: closed, because the owner archived Atlas (ADR 0005).
