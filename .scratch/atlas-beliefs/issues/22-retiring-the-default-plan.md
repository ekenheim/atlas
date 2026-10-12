# 22: Retiring the default investigation plan and the machine edge review

Type: build
Status: open
Blocked by: 21

## What to build

The default plan and `review_relationships` leave the product: `POST /investigations` refuses a plan other than `argument`; the edge table, exceptions queue and `review_relationships` routes read-only for one release, then removed with their pages; Relationships stay as evidence links a Belief may cite. Tests of the default plan move to the bulk-mode tests or go; `docs/decisions.md` records it.

## Acceptance criteria

- [ ] Suite green; production's queue shows no default-plan jobs; the nav has no Relationships or Exceptions entries after the second release.
