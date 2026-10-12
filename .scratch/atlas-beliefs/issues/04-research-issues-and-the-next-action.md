# Issues: research work that narrows and requires, and the next action by rule

Type: build
Status: open
Blocked by: 02

Spec §2. Tables `issue`, `issue_edge`, `issue_product`; the card's open questions, `not_read` companies and `unknown` steps become Issues under the investigation's root Issue; `GET /api/v1/issues?theme=&status=`, `POST /api/v1/issues` (narrow, require), `POST .../complete|abandon`, `GET /api/v1/issues/next?theme=` by the rule in §2. A follow-up round takes the next Issue as its question when none is given.

## Done when

- [ ] Tests at the seams; one investigation's open questions appear as Issues and `next` returns the rule's choice.
