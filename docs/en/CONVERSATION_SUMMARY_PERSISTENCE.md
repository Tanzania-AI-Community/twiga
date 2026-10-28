# Conversation summary persistence

The PostgreSQL foundation stores summary data separately from `messages`.
`conversation_summary_state` has at most one row per user: an older-history
rollup, its token count, the last compacted batch sequence, a version and an
update time. The row defaults to an empty rollup, zero count, boundary and
version; the first successful API write creates it with version 1.
`conversation_summary_batches` stores ordered per-user summaries and their
source coverage. Both tables reference users with `ON DELETE CASCADE`.

Batch sequence numbers are positive and unique per user. Batch endpoints are
the first and last sources in `(created_at, id)` order, with positive IDs and
nondecreasing timestamps. They are descriptive metadata, not coverage
watermarks: IDs can have gaps or arrive later. The nonempty JSON array of
`covered_message_ids` records exact membership, including for compacted
batches. The state version and boundary are nonnegative, its rollup count is
between 0 and 25,000, and batch counts are nonnegative. New batches default to
uncompacted; timestamps default to the current time. Compacted rows must have
empty text and zero tokens. The schema indexes active batches by user and
sequence.

## Reading a snapshot

`get_conversation_summary_snapshot(user_id)` uses a short, read-only
repeatable-read transaction. It returns detached immutable data: the rollup,
version, next sequence, active batches, all exact covered IDs and eligible
pending sources. With no state, the version is `None`, the rollup is empty and
the next sequence is 1. Pending sources belong to the user, are marked present
in the conversation, and have system, user or assistant role. Assistant messages
with tool calls and content starting with `[FLOW_SENT]` or `[FLOW_COMPLETED]`
are excluded. Empty eligible content is represented as an empty string. Pending
sources are ordered by creation time and ID and exclude IDs covered by any
batch, including compacted ones. The snapshot is coherent at its transaction's
view; later arrivals require a new snapshot.

## Writing a batch

`commit_conversation_summary` accepts a prepared `SummaryUpdate` and performs
a version-checked append, optionally with a rollup update, in one transaction.
For an absent state, `expected_version=None` inserts it conflict-safely; for an
existing state, the expected version must match and is incremented. A competing
first writer or version mismatch returns `STALE`; a successful transaction
returns `COMMITTED`. Invalid plans raise `ValueError`, including invalid or
repeated IDs, overlap with existing coverage, missing, ineligible or wrongly
ordered sources, and a mismatched next sequence. Database failures propagate;
invalid or failed writes roll back the state change and batch together.

A candidate has nonblank summary text and a caller-supplied count from 0 to
75,000. The total count of remaining active batches plus the new batch cannot
exceed 75,000. An optional rollup needs nonblank text, a count from 0 to 25,000,
and a nonempty prefix of the existing active batches in sequence order. The
prefix must leave the latest five batches active when the new batch is included.
The API validates supplied counts and boundaries; it does not decide when to
summarize or compact, calculate token counts, or call a model.

Compaction replaces the older rollup and marks that prefix compacted, clearing
its summary text and count while retaining its exact coverage and endpoints.
The new batch, rollup, archival changes and version update commit atomically.
Original message rows and user activity are unchanged. Generate and count
candidate text outside these persistence transactions; after a stale result,
a caller needs a fresh snapshot before deciding what to write.

## Migration and checks

See [migration guidance](MIGRATIONS.md#conversation-summary-schema-issue-92)
for prerequisites and downgrade effects, and the [test command](CONTRIBUTING.md#conversation-summary-persistence-checks)
for the disposable database setup.

`test_conversation_summary_db.py` checks model defaults and constraints,
eligibility, detached snapshot behavior, invalid plans and stale versus failure
handling without PostgreSQL (portable constraints use SQLite). Its PostgreSQL cases exercise exact coverage,
ordering, isolation, concurrent writers and snapshots, rollback, compaction,
limits, sequence uniqueness and user-deletion cascades. The migration module
checks model/schema parity and generated SQL offline; its PostgreSQL case runs
the parent chain and upgrade/downgrade/upgrade while checking retained users and
messages. Offline checks cannot establish PostgreSQL transaction, race or
migration behavior; skipped PostgreSQL cases leave those checks outstanding.
