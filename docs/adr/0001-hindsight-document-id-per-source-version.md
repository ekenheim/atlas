# Hindsight document IDs are per Source Version UUID and section, not content hash

Hindsight 0.10.1 treats `document_id` as a destructive upsert key: re-retaining an ID deletes the earlier extraction's facts (verified; see `docs/hindsight-feature-matrix.md`). The spec suggested `srcv:<sha256>`. But identical bytes can legitimately appear under two Source Documents, and a hash-keyed retain of the second would silently replace the first's metadata link. So Atlas retains each filing section as `srcv:<source_version_uuid>:<section-anchor>`, submitted as one batch per Source Version. Before retaining, it checks whether a Source Version with the same raw hash is already retained; if one is, it links the new one to it instead of retaining again.

## Consequences

- An ID is never reused, so no retain can destroy another Source Version's memories.
- Provenance resolves from a memory's `document_id` and `metadata.source_version_id` straight to the ledger row and section.
- Changing the scheme later means re-retaining every bank, which is why this is recorded.

## Amendment (2026-09-29): resubmitting the same content

"Never reused" means an ID is never used for **different** content. Resubmitting the *same* content under the same document ID is allowed: the one reprocess of a zero-fact section, and the resubmission of a batch whose operation failed for quota or an outage (ticket 14). Hindsight's upsert then replaces only that document's own extraction with an extraction of identical content, so nothing another Source Version or section retained is touched, and nothing is lost that the resubmission doesn't bring back. A revised Source Version still gets new IDs (its own UUID), so different content never lands under an existing ID.
