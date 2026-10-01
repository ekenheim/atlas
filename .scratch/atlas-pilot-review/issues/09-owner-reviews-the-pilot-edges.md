# The owner reviews the pilot's edges

Type: task
Status: open
Blocked by: none

## Question

The owner's review decisions from the 0.2.3 run of investigation 1 are still open (`.scratch/pilot/results.md`, "Corrections needed"). They are the owner's acts (`POST /api/v1/relationships/{id}/review`, or the exceptions page):
- approve Lumentum `capacity_constrained` (the allocation statement), in the exceptions queue;
- reject the three boilerplate Lumentum `sole_sources` edges (two in the exceptions queue, one `machine_reviewed`) and Coherent's Industrial-segment `sole_sources`;
- reject Coherent `expands_capacity_for` 6-inch GaAs VCSEL manufacturing facilities (`machine_reviewed`; the verb belongs to the InP clause).

The lead prepares the list with each edge's ID and link; each later investigation's "Corrections needed" is added here. Resolved when the exceptions queue holds no pilot edge and the answer records what the owner decided.
