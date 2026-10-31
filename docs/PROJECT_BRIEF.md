# Teleport: Project Brief (source of truth for the workflow)

Teleport keeps a running workload accessible across devices. When a workload must leave its device, Teleport decides whether it can be safely migrated with its state preserved, or must keep running where it is and be accessed remotely. Both outcomes always come with reasons.

## Team and folders
- P1 Core, migration engine, integration lead: contract/, docs/, scripts/, sdk/, agent/teleport/core/, agent/teleport/migration/, agent/teleport/authority/, tests/core/, tests/migration/, all build, config and package files
- P2 Device agent, transport, security: agent/teleport/devices/, agent/teleport/transport/, agent/teleport/security/, dev/devices/, dev/transport/, tests/devices/, tests/transport/, tests/security/
- P3 Feasibility, orchestration, history: agent/teleport/feasibility/, agent/teleport/orchestration/, agent/teleport/history/, dev/feasibility/, dev/orchestration/, tests/feasibility/, tests/orchestration/, tests/history/
- P4 Remote access, dashboard, demo: ui/, agent/teleport/remote/, examples/, demo/, dev/remote/, tests/remote/, tests/ui/
Only edit your own folders. Contract changes are requested from P1.

## Architecture
Every device runs one Teleport agent (Python 3.11, FastAPI, port 8765 by default). The agent serves the REST and WebSocket API, the dashboard (ui/, React) and the encrypted peer link to other agents. Modules talk through a typed async event bus (ctx.bus) and the Protocols in contract/contract.py, so each module is testable with mocks. Dev mode runs two agents on one laptop: A on 8765 and B on 8766, each with its own TELEPORT_HOME folder and an optional simulated device profile.

## Module entry points (agreed names)
- create_device_service(ctx) in agent/teleport/devices/__init__.py (P2): local_info(), list_devices(), latest_stats(device_id), set_override(device_id, partial_stats or None). Publishes stats.update.
- create_peer_link(ctx) in agent/teleport/transport/__init__.py (P2): pair(addr, pin), connect(device_id), send(device_id, PeerMessage), on_message(handler), link_quality(device_id), list_peers(). Publishes link.update, device.paired, device.lost.
- SecureSession in agent/teleport/security/ (P2): identity keys, key exchange, encrypt/decrypt, sign/verify manifests.
- create_feasibility_engine(ctx) in agent/teleport/feasibility/__init__.py (P3): evaluate(manifest, source, target, link) -> FeasibilityResult.
- create_orchestrator(ctx) in agent/teleport/orchestration/__init__.py (P3): watches stats and link events, publishes recommendation, triggers migration in auto mode.
- create_history_store(ctx) in agent/teleport/history/__init__.py (P3): SQLite store for devices, migrations, decisions, events.
- create_migration_manager(ctx) in agent/teleport/migration/__init__.py (P1): start(workload_id, target_id, trigger), abort(id), status(id), list(). Publishes migration.status and authority.change.
- create_authority_service(ctx) in agent/teleport/authority/__init__.py (P1).
- create_remote_service(ctx) in agent/teleport/remote/__init__.py (P4): host side (screen capture, input injection) and the viewer WebSocket. Publishes remote.session.
- Dashboard in ui/ (P4). Context, event bus, settings and app factory live in agent/teleport/core/ (P1).

## Workflow
1. Trigger: Device A runs low on resources (battery, CPU, memory, connectivity), or Teleport predicts a problem from A's stats and recommends migration, or the user commands it. Settings choose recommend-only or auto.
2. A connects to B. The devices are paired once, then authenticated and encrypted. The link is wifi or a data cable (a cable is a point-to-point network link such as USB tethering or direct ethernet; the agent detects the link type and prefers the cable).
3. The feasibility engine checks CPU architecture, OS, runtime version, library dependencies, RAM, CPU cores, storage, GPU, and network quality, then decides MIGRATE or REMOTE_ACCESS (or STAY if neither works) with a reason for every check.
4a. MIGRATE, in checkpoints. The workload manifest defines user-chosen checkpoints (named units of state such as config, database, model, working files). They are transferred one by one and each one is hash-validated on B. While they transfer, A keeps running and keeps authority. If only 5 of 10 are on B, authority does not move and B does not start. When all are validated, cutover: A takes a final checkpoint of anything that changed, is FENCED (paused, epoch + 1), B receives the changed checkpoints, gets authority and starts from the restored state. Only after B confirms it started does A terminate its copy. If anything fails before B confirms, ROLL BACK: B discards its copy and A is unfenced and resumes with its live state.
4b. REMOTE_ACCESS. The workload keeps running on A with A's resources. B shows A's screen (duplicated display) and sends mouse and keyboard input to A, like AnyDesk. A must give consent.
5. Everything is saved (devices, migrations, decisions with reasons) and can be revisited in the History page.

## Authority (single active instance)
Per workload there is one lease: holder device, integer epoch, state SOURCE | FENCED | TARGET. Only the holder may run the workload. Handover: SOURCE -> FENCED (epoch + 1) -> TARGET. Rollback: FENCED -> SOURCE. Any start request, message or chunk carrying an older epoch is rejected. After a crash or reconnect, devices compare epochs and the one with the lower epoch stops.

## Feasibility rules (each gives pass, warn or block with a reason sentence)
Architecture match; OS compatible; runtime present and version >= required; every library present; free RAM >= required x 1.2; CPU cores >= required; free disk >= snapshot size x 2 + required; GPU present if needed; target battery not low and target online; link quality good enough to transfer in a sane time (RTT, Mbps, loss). A block on arch, OS, runtime, libs, RAM, CPU, disk or GPU means REMOTE_ACCESS if the workload is remoteCapable and the link can stream, else STAY. Warnings alone still allow MIGRATE.

## Security
One-time PIN pairing exchanges Ed25519 identity keys. Each session uses X25519 key exchange plus HKDF and AES-256-GCM on every message and chunk. Snapshots are validated by per-chunk SHA-256, per-checkpoint SHA-256 and a manifest signed by the source device key. Remote access needs consent on the host. No secrets in git.

## Other features
Prediction (battery time-to-empty trend); history with revisit; wireless or cable transport; performance monitoring (feasibility, resource use, transfer progress, interruption time, reasons); stats simulator to demo low battery or high CPU (always labeled SIMULATED); recommend or auto mode.
Stretch: process-level checkpoint with CRIU on Linux, microphone forwarding in remote access, delta compression, QR pairing.

## Budgets
Stats refresh 1 s; feasibility result < 500 ms; interruption time (fence to target running) reported and under 3 s for the demo workload; remote view >= 10 FPS at 720p on a LAN.

## Rules
Python 3.11 fully typed, TypeScript strict. Only edit your own folders. Nobody except P1 edits pyproject.toml, package.json or build config. No secrets in git. Simulated data must be labeled.
