# Migration protocol (as implemented)

Code: `agent/teleport/migration/manager.py` (source and target sides) and `agent/teleport/authority/`.
Tests and mocks: `tests/migration/` (`mocks.py` has an in-memory PeerLink pair with fault injection).

## Source (device A)

| Phase | What happens |
| --- | --- |
| CONNECTING | `peers.connect(target)`; the link type comes from `peers.link_quality(target)` |
| EVALUATING | `feasibility.evaluate(...)`; the decision is logged with `history.log_decision` |
| REMOTE_ACCESS | `remote.start_session(workload, viewer=target)`, then end |
| FAILED | STAY (`error` lists the block reasons), or a failure before anything was offered |
| TRANSFERRING | live checkpoint (A keeps running), `mig.prepare` (signed), then every unit in 256 KB `mig.chunk`s (window of 8, resent on a nack or timeout, up to 3 retries) |
| VALIDATING | wait for `mig.validated ok` (target checked every chunk and unit hash) |
| FENCING | final checkpoint, pause, `authority.fence` (epoch + 1), `mig.fence`, then `mig.fenced {changed}` and the changed units at the new epoch, then `mig.validated` again |
| STARTING_TARGET | `mig.start {epoch}`, wait for `mig.started` |
| COMPLETED | `authority.grant(target)`, then A's copy is killed (never resumed). `interruptionMs` runs from the pause to `mig.started ok` |
| ROLLING_BACK, ROLLED_BACK | any failure, timeout, abort, `mig.abort` from the target or `device.lost` before `mig.started ok`: send `mig.abort`, roll FENCED back to SOURCE (epoch + 1), resume A |

An abort that arrives after `mig.start` was sent waits for the target's answer. If the target
already started, the migration completes with an `abort.late` warning, so two copies never run.

The workload folder travels as an extra system unit, `teleport.code`. Ids starting with `teleport.` are reserved.

## Target (device B)

- `mig.prepare`: verify the signature, the epoch, that the workload is not running here, and that every manifest checkpoint is offered. Staging goes to `TELEPORT_HOME/workloads/<id>/staging/<migrationId>/`. Reply `mig.ready`.
- `mig.chunk`: reject an older epoch or a bad SHA-256 (`mig.chunkAck ok=false`), otherwise ack. A complete unit is hash-checked and staged.
- `mig.start` is refused unless every unit is validated, the source fenced, and the epoch is the fence epoch. On success: commit to the checkpoint store, unpack the code, `authority.grant(self)`, start through the runner with restore, reply `mig.started`.
- `mig.abort` or `device.lost` before start: discard staging. `mig.abort` after B started (A never got the ok): B kills its copy and releases.

## Authority

`TELEPORT_HOME/authority.json`, one lease per workload, this device's view. Epochs only grow:
fence +1, rollback +1. `may_run()` is true only for the holder in SOURCE or TARGET.

## Needed from the peer link (P2)

- Publish `device.lost` when a peer drops; migrations rely on it to roll back quickly.
- Implement `sign_manifest(payload) -> str` and `verify_manifest(deviceId, payload, signature) -> bool`
  (the `ManifestSigner` Protocol in manager.py) with the Ed25519 identity keys. Until then a SHA-256
  digest is used: integrity only, no authenticity.
- Deliver messages from one peer in order (chunks may be acked out of order, but `mig.fence`,
  `mig.fenced` and `mig.start` must arrive after the chunks sent before them).
