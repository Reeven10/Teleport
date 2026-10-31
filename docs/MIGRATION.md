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

## Continuity and recovery

Every migration (source and target side) is journaled to `TELEPORT_HOME/migrations/<id>.json` on
each status change. The runner keeps `workloads/<id>/workload.json` (registry) and `run.json` (pid),
so a restarted agent knows its workloads, kills orphaned processes and relaunches what it holds.

| Restarted side, phase when it died | Decision |
| --- | --- |
| Source, before `mig.start` (CONNECTING to STARTING_TARGET, fenced or not) | Roll back (FENCED to SOURCE, epoch + 1), relaunch from checkpoints |
| Source, after `mig.started ok` (or its lease shows the target) | Stays stopped, COMPLETED |
| Source, `mig.start` sent, no answer | Stays fenced and waits for the target's lease: target holds it means COMPLETED, otherwise roll back and resume |
| Target, staging only | Discard staging |
| Target, authority granted, start not confirmed | Held, not relaunched: the source's lease decides (source shows target holds it means start, source FENCED means wait, else release) |

The same "wait for the lease" rule applies live: if the link drops or `mig.started` times out after
`mig.start` went out, the source does not roll back blindly. An operator `POST /api/migrations/{id}/abort`
on a waiting migration forces the rollback (the guard below then stops the target if it did start).

## Split-brain guard

Connected agents exchange `auth.leases` every `leaseSyncS` seconds (default 5) and right after a link
appears. When both devices hold the same workload in SOURCE or TARGET, the higher epoch wins; on equal
epochs TARGET beats SOURCE, then the smaller device id wins. Both sides compute the same answer. The
loser kills its copy and adopts the winner's lease, and both publish `authority.conflict` (once).

## Delta transfer, pre-copy, settings

- `mig.ready.have` lists the units the target already holds with the same SHA-256 (its checkpoint store,
  or `workloads/<id>/cache/` filled by pre-copy and by earlier code units). Those are not sent again, so
  migrating back and forth only moves what changed.
- Pre-copy: `POST /api/workloads/{id}/precopy {targetId}`, or on a timer with `precopyIntervalS`
  (0 = off) to `precopyTargetId` (empty = first connected peer). No authority change; not listed as a migration.
- `PUT /api/settings`: `chunkSizeKb` (16 to 512; chunks travel base64 in one peer frame), `precopyIntervalS`,
  `precopyTargetId`, `leaseSyncS`.

## Metrics

`MigrationStatus.metrics` and `GET /api/migrations/{id}/metrics` give the link type, chunk size, total
duration, interruption (pause to `mig.started ok`), bytes done, total and skipped, overall throughput,
and per checkpoint transfer (stage initial, delta or precopy; chunks, retries, ms, Mbps, skipped).
