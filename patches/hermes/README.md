# Hermes patch queue

`vendor/hermes` is generated from the source pinned in
`vendor/hermes-upstream.json`. Keep xbot-owned tools and integration code under
`src/xbot`; add a patch here only when an upstream source change is unavoidable.

Patch paths are relative to the Hermes repository root. Add each filename to the
manifest's `patches` array in application order. `scripts/sync_hermes.py` applies
them with `git apply` before replacing the vendored tree.
