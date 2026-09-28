# Hindsight document IDs are per Source Version UUID and section, not content hash

Hindsight 0.10.1 treats `document_id` as a destructive upsert key: re-retaining an ID deletes the earlier extraction's facts (verified; see `docs/hindsight-feature-matrix.md`). The spec suggested `srcv:<sha256>`. But identical bytes can legitimately appear under two Source Documents, and a hash-keyed retain of the second would silently replace the first's metadata link. So Atlas retains each filing section as `srcv:<source_version_uuid>:<section-anchor>`, submitted as one batch per Source Version. Before retaining, it checks whether a Source Version with the same raw hash is already retained; if one is, it links the new one to it instead of retaining again.

## Consequences

- An ID is never reused, so no retain can destroy another Source Version's memories.
- Provenance resolves from a memory's `document_id` and `metadata.source_version_id` straight to the ledger row and section.
- Changing the scheme later means re-retaining every bank, which is why this is recorded.
