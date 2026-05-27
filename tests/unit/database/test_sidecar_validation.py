"""Regression: large Turso generation values must NOT be flagged as corrupt.

History: an earlier fix (`fix(sync): backup .db + sidecars on corrupt
generation`) assumed pyturso wrote sentinel ~10^18 generations on sync
errors, and forced a full re-bootstrap whenever it saw one. The assumption
was wrong — Turso server encodes legitimate generations near 10^18 (likely
as `(10^18 - 1) - real_generation`), so a healthy DB freshly pulled from
the server would carry e.g. `999999999999999998` in its `.db-info` and
be falsely flagged. Result: every startup wiped the local copy and
re-downloaded the entire DB.

This file pins down the lesson so the check doesn't get re-introduced.
"""
from __future__ import annotations


def test_sidecar_corruption_check_was_removed():
    """The helper that misclassified Turso's normal generations as corrupt
    has been removed. Re-introducing it would cause repeated full
    re-bootstraps on healthy databases — see the history backup files
    `data/*.db.er-broken-*` for evidence the bug fired in production."""
    import database.backends._pyturso as mod
    assert not hasattr(mod, "_has_corrupt_sidecar_generation"), (
        "_has_corrupt_sidecar_generation reintroduced — it misclassifies "
        "Turso's normal server-side generation encoding (~10^18) as a "
        "corruption sentinel. Don't bring it back."
    )
    assert not hasattr(mod, "_CORRUPT_GENERATION_THRESHOLD"), (
        "_CORRUPT_GENERATION_THRESHOLD reintroduced — see comment above."
    )


def test_real_observed_generations_are_documented():
    """Values observed in production after a successful Turso pull. Kept
    here so the rationale for the removal is greppable from the test
    suite."""
    real_world_generations = [
        999999999999999998,  # history-asher.db-info, post-pull, healthy
        999999999999999999,  # momo-users-hub.db-info, post-pull, healthy
        999999999999999996,
        999999999999999928,
    ]
    # All look like (10^18 - 1) - small_integer.
    for g in real_world_generations:
        delta = (10**18 - 1) - g
        assert 0 <= delta < 1000, (
            f"Unexpected encoding for {g} (delta from 10^18-1 = {delta}); "
            f"refine our understanding of Turso's generation scheme."
        )
