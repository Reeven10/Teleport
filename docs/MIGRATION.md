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
| TRANSFERRING | live checkpoint (A keeps running), `mig.prepare` (signed), then every unit in 256 KB `mig.chunk`s (window of 4, resent on a nack or after 20 s without an ack, up to 3 retries) |
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

## Cutover (the freeze window)

The workload only stops between the pause and `mig.started ok` (`interruptionMs`). To keep that short:

1. **Full transfer while live.** Every unit the target does not already hold (by SHA-256) is sent while
   the workload runs and keeps authority.
2. **Catch-up rounds, still live.** Up to 3 rounds: ask for a fresh checkpoint, resend only the units
   whose hash changed. Stop when a round has at most 64 KB left (`Timeouts.catchup_rounds` / `catchup_bytes`).
3. **Freeze.** Pause, fence (epoch + 1), pack manifest paths (only if the manifest has any), send only
   the units that changed since the last round. If nothing changed, no extra round trip.
4. **Start.** The target moves the already verified units into its store (a rename, no re-hash),
   unpacks the code, takes authority, starts, and answers.

`MigrationMetrics.cutover` splits the interruption into `fenceMs`, `deltaMs` (with `deltaBytes`) and
`startMs`, plus `catchupRounds`.

Measured on this laptop over the real peer link (P2 transport, AES-256-GCM), `scripts/bench_transfer.py`,
20 MB checkpoint, 256 KB chunks: **interruption 53 to 59 ms** (fence 7, delta 4, target start 37 to 43).
That was about 155 ms before the rename-commit and the empty-delta skip.

counter_job on real agent subprocesses (as with `dev:two`), migrated A->B->A->B (epochs 1 to 4, return
trips skip the unchanged units): **interruption 183 to 193 ms**. Fence about 20 ms (suspend + fence +
pack the journal path), delta about 52 ms (four small units, sent concurrently), target start about
107 ms (unpack + launch a Python process on Windows). Total migration about 1.0 to 1.25 s.

## Tuning

Defaults: `chunkSizeKb` 256, window 4 chunks in flight (ack timeout 20 s, tuned for wifi), gzip level 6 (`compressLevel`).

| chunk KB | window 4 | window 8 | window 16 |
| --- | --- | --- | --- |
| 64 | 38.6 Mbps | 54.4 | 40.5 |
| 128 | 47.1 | 41.4 | 74.6 |
| 256 | 79.4 | 79.6 | 77.1 |
| 512 | 82.6 | 81.1 | 80.6 |

These are loopback numbers, CPU-bound and noisy (±20 %). Below 256 KB the per-chunk overhead dominates.
256 and 512 are equal, and 256 resends half as much after a corrupt chunk. On a real link with RTT, a
bigger window helps: raise `Timeouts.window`. The ceiling (~80 Mbps) comes from the transport encoding:
the chunk is base64 inside JSON, encrypted, then base64 again in a text frame (issue P2-13).

Compression: units are tar.gz already, so the wire adds none. `compressLevel` 0 (store) is fastest
for data that is already compressed (models, media). 1 is a good middle ground. 6 is the default.
It applies to agent-packed and SDK-packed units (`TELEPORT_COMPRESS_LEVEL` for workloads).

Event loop: packing, hashing, snapshots, chunking, the target's whole-unit check and the commit run in
worker threads (`asyncio.to_thread`), so heartbeats, stats and other migrations are not blocked.

## Rollback rules

| When it fails | Result | Authority | Source | Target |
| --- | --- | --- | --- | --- |
| Before anything was offered (unreachable, workload gone) | ROLLED_BACK | unchanged | keeps running | nothing |
| Feasibility says STAY | FAILED (with reasons) | unchanged | keeps running | nothing |
| During transfer or validation: lost link (after a 5 s reconnect try), timeout, corrupt chunk after 3 resends, target refusal, disk full, abort | ROLLED_BACK | unchanged | keeps running | staging discarded |
| The workload exits during the transfer | ROLLED_BACK | unchanged | stays stopped (it exited) | staging discarded |
| During the freeze, before `mig.start` | ROLLED_BACK | FENCED to SOURCE, epoch + 1 | resumes (live state) | staging discarded |
| `mig.start` out, no answer (link lost, timeout) | waits in STARTING_TARGET | stays FENCED | stays paused | decides by itself |
| ...then the target's lease shows it holds the workload | COMPLETED | moves to target | stopped | running |
| ...then the target's lease shows it does not | ROLLED_BACK | FENCED to SOURCE, epoch + 1 | resumes | discarded |
| `mig.started ok=false` (start failed) | ROLLED_BACK | FENCED to SOURCE, epoch + 1 | resumes | discarded, lease released |
| User abort after `mig.start` | waits for the answer; COMPLETED (with an `abort.late` warning) or ROLLED_BACK | | | |
| Any restart in between | see "Continuity and recovery" above | | | |

Never two copies: the source only resumes when the target provably does not hold the workload, and
the target only starts when every unit is validated, the source is fenced and the epoch matches.

## Failure messages

`MigrationStatus.error` is one short sentence for the dashboard (10 to 160 characters, no stack
traces or device ids), for example:

- "Lost the link to the target (transferring)."
- "Checkpoint c3 could not be sent intact (failed after 4 attempts)."
- "The target refused: Not enough disk space on the target: 61 MB needed, 0 MB free."
- "The target cancelled: The target ran out of disk space."
- "The target could not start the workload: simulated start failure."
- "The workload stopped during the transfer (exit code 3); nothing to hand over."
- "The target did not answer in time (validating)."
- "Aborted by user."

The technical detail, when there is one, is in the reasons as `error.detail` and in the agent log.
A `rollback` reason repeats the message with severity block.

## Known limits

- **Cooperative checkpoints only.** State moves only through what the workload saves with the SDK
  (`teleport.checkpoint`, `on_fence`) and the manifest's paths. There is **no live process memory
  snapshot** (no CRIU yet): anything the job keeps only in memory and has not checkpointed is lost.
  Progress between the final checkpoint and the pause (a few milliseconds) is also lost.
- After an agent crash, the source resumes from its last checkpoint, not from the live process.
- A real network split during STARTING_TARGET can leave the source waiting (stopped) until the link
  returns or an operator aborts. If the operator aborts while the target did start, the split-brain
  guard stops the target once they reconnect (lower epoch).
- Pre-copy sends what is already saved; it does not ask the job for a fresh checkpoint.
- Throughput is capped by the transport encoding (P2-13), not by the migration engine.
