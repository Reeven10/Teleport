# Integration 1: issues by owner

Found while wiring main (P2 devices/transport/security, P3 feasibility/history, P4 remote/dashboard)
into the core and the migration manager, and running `npm run dev:two` plus
`pytest tests/migration/e2e`. Each section can be pasted into that owner's next prompt.
P1 worked around nothing silently; every workaround is named below with the issue it waits on.

## P2: devices, transport, security

**P2-1. Agents advertise LAN addresses they do not listen on.**
- File: `agent/teleport/devices/capabilities.py` (`get_network_addresses`), used by `transport/link_detector.py` (`select_best_address`).
- Symptom: with the default bind `127.0.0.1` (and in `npm run dev:two`), `DeviceInfo.addrs` lists every LAN IP (e.g. `192.168.56.1:8766`, typed `cable`). `connect()` picks the cable address first, so the peer link fails with "connection refused".
- Repro: start two agents without `TELEPORT_FORCE_LINK` on a machine with a LAN adapter, pair them, then call `peers.connect(B)` and look at the error.
- Fix: only advertise addresses reachable through `ctx.settings.host`. Bound to loopback means only `127.0.0.1:<port>`; bound to `0.0.0.0` means all interfaces; otherwise just that IP.
- P1 workaround: `core/app.py` calls `peers.set_forced_link("loopback")` when the agent is bound to loopback. Remove it once this is fixed.

**P2-2. Nobody sends `peer.stats`, so a dashboard never sees the peer's live stats.**
- File: `agent/teleport/transport/service.py`.
- Symptom: `record_peer_stats` exists, but no code sends `PeerStats`. A's `/api/stats` and `/ws/events` only had A's stats, so scenario 1 failed.
- Fix: in the peer link, send `PeerStats` for every local `stats.update` to each connected peer. On receive, after `record_peer_stats`, publish `StatsUpdateEvent` on the local bus.
- P1 workaround: `agent/teleport/core/relay.py` does exactly this through the PeerLink Protocol. Delete it, and its registration in `core/app.py`, once the transport does it.

**P2-3. `GET /api/pair` returns the pairing PIN to anyone who can reach the agent.**
- File: `agent/teleport/transport/service.py` (`get_pair_info`).
- Symptom: with `TELEPORT_HOST=0.0.0.0`, any device on the LAN can read the PIN and pair, which defeats PIN pairing.
- Repro: `curl http://<agent-ip>:8765/api/pair` from another machine.
- Fix: serve the PIN only to loopback clients (check `request.client.host`), or show it only in the host's dashboard and agent log. The e2e tests read it from loopback, which stays allowed.

**P2-4. Traffic is still plaintext, and the dashboard says AES-256-GCM.**
- File: `agent/teleport/security/dev_session.py`. `PlaintextDevSession` is used for every connection (`transport/connection.py`).
- Fix: the planned Ed25519 + X25519 + HKDF + AES-256-GCM session. Until then, P4 must not show "AES-256-GCM" (see P4-3).

**P2-5. The peer link cannot sign migration manifests.**
- File: `agent/teleport/transport/service.py`.
- Symptom: `mig.prepare` falls back to a SHA-256 digest (`migration/manager.py` `DigestSigner`), which checks integrity, not who sent it.
- Fix: implement `sign_manifest(payload: bytes) -> str` and `verify_manifest(device_id: str, payload: bytes, signature: str) -> bool` on `PeerLinkService`, with the Ed25519 identity key and the peer's key stored at pairing. Migration picks them up automatically (the `ManifestSigner` Protocol).

**P2-6. `pair()` special-cases `addr == "x"`.**
- File: `agent/teleport/transport/service.py` (`pair`).
- Symptom: `addr "x"` raises NotImplementedError. This existed only to keep an old P1 test passing; that test now uses an unreachable address and expects 502.
- Fix: delete the special case.

**P2-7. `/api/devices` takes about 0.4 s and writes `devices.json` on every call.**
- Files: `agent/teleport/devices/service.py` (`list_devices` and `local_info` call `probe_local_device` and `registry.upsert`, which saves the file each time).
- Repro: `time curl localhost:8765/api/devices` gives about 0.4 s. `local_info()` is also called by feasibility, migration, the stats relay and every peer hello.
- Fix: probe capabilities once at startup (and refresh on a timer if needed), cache `local_info()`, and only save the registry when something changed.
- Impact confirmed after merging main (2026-11-01): `local_info()` runs synchronously on the event loop, so any caller blocks the agent for ~0.4 s. When the stats relay and lease sync called `peers.list_peers()` every second, a 126-byte chunk took 785 ms and the interruption time reached 3.3 s (budget 3 s).
- P1 workaround: `core/peers.py` (`PeerDirectory`) keeps known peer ids from events, so P1 code no longer calls `list_peers()` in loops. Feasibility, migration start and each `/api/devices` call still pay the probe until this is fixed.

## P3: feasibility, orchestration, history

**P3-1. Imports through `agent.teleport...` load the package twice.**
- Files: `dev/feasibility/cli.py:16`, `tests/feasibility/test_checks.py:7`, `tests/feasibility/test_engine.py:7`, `tests/history/test_history.py:10-14`.
- Symptom: `npm run typecheck` fails with "Source file found twice under different module names". At runtime, `agent.teleport.core.context.Context` is a different class from `teleport.core.context.Context`, so isinstance checks and bus subscriptions can silently fail.
- Fix: import `teleport...` (for example `from teleport.feasibility.engine import evaluate_feasibility`).
- P1 workaround: these files are excluded in `mypy.ini`. Drop the exclusions once they're fixed.

**P3-2. `tests/feasibility/fixtures/__init__.py` is not strictly typed.**
- Lines 18 and 22 (`dict` without type arguments; returns `Any`).
- Fix: `dict[str, Any]` and an explicit `cast`. Also excluded in `mypy.ini` for now.

**P3-3. `npm run lint` fails on 25 ruff errors, all in P3 files.**
- Files: `agent/teleport/feasibility/checks.py` (12, lines too long), `engine.py:125`, `dev/feasibility/cli.py`, `tests/feasibility/test_checks.py` and `test_engine.py` (mutable default arguments `arch=["x86_64"]`), `test_cli.py`, `tests/history/test_history.py` (unused imports).
- Repro: `node scripts/py.mjs -m ruff check agent/teleport/feasibility dev/feasibility tests/feasibility tests/history`.
- Fix: wrap long reason strings, use `None` defaults, remove unused imports. P1 did not touch these files.

**P3-4. Every `evaluate()` logs a decision, so history gets duplicates with the wrong trigger.**
- File: `agent/teleport/feasibility/__init__.py` (`FeasibilityEngineImpl.evaluate` publishes `DecisionLoggedEvent` with `trigger="user_command"` and no `migrationId`).
- Symptom: one `POST /api/feasibility` preview plus one migration gives 3 rows in `/api/history/decisions`: the migration's own entry (right trigger, with `migrationId`) plus 2 anonymous ones.
- Fix: make `evaluate()` a pure query. The caller logs the decision (the migration manager already does, through `history.log_decision`; the orchestrator should do the same for recommendations).

**P3-5. The orchestrator was not merged.**
- File: `agent/teleport/orchestration/__init__.py` is still the P1 stub.
- Symptom: there is no `recommendation` event, no prediction, and no auto mode.
- Fix: merge the orchestrator. When the trigger fires, call `ctx.migration.start(workload, target, trigger)` in auto mode, or publish a `recommendation` in recommend mode.

## P4: remote access, dashboard

**P4-1. The dashboard shows mock devices even when the agent is live.**
- Files: `ui/src/store/reducer.ts:7-8` (`thisDeviceId: 'device-a'`, `peerDeviceId: 'device-b'`), `:20` (`mockFeederActive: true`), and `INIT_REST` (keeps `thisDeviceId` if `deviceMap[thisDev]` exists, which the mock init just created).
- Symptom: on `npm run dev:two` the dashboard shows "Device A (MacBook Pro M2)" and "Device B (Workstation Tower, RTX 4080)" and "Active Devices: 4". Turning the mock feeder off keeps the mock cards. The real devices (`dev-...`) never render, although `fetch('/api/devices')` from the page returns both.
- Repro: `npm run dev:two`, open http://localhost:5173, then in the console run `document.querySelectorAll('[data-testid^=device-card]')`, which returns `device-card-device-a` and `device-card-device-b`.
- Fix: start with the mock feeder off, and turn it on only when `/api/health` fails. When real data arrives, drop the mock devices, stats and migration state. Take `thisDeviceId` from `/api/health` `deviceId`, and the peer from the first other device in `/api/devices`.

**P4-2. No remote view is offered for a REMOTE_ACCESS decision.**
- Files: `ui/src/pages/RemotePage.tsx` and `MigrationPage.tsx` are placeholders.
- Symptom (scenario 3): the backend ends with phase `REMOTE_ACCESS`, publishes `remote.session` (pending consent, `viewerId` = B) and lists it in `GET /api/remote/sessions`, but the dashboard shows nothing.
- Fix:
  - **On the host (A):** on `remote.session` with `consent: false`, show a consent prompt that calls `POST /api/remote/consent`.
  - **On the viewer (B):** open the viewer (`/ws/remote/{sessionId}?token=...`, token from `GET /api/remote/token/{id}`) and show the reasons from the migration status.
  - **Migration page:** show phase, per-checkpoint sent/validated, bytes, `interruptionMs`, and the reasons, including the `rollback` reason (scenario 4).

**P4-3. The Link card claims AES-256-GCM, and the header says "encrypted WebSocket".**
- Files: `ui/src/components/dashboard/LinkCard.tsx:65`, `ui/src/pages/DashboardPage.tsx:29`.
- Symptom: the session is plaintext today (P2-4), and `/ws/events` is a local, unencrypted WebSocket. In the live view the card also showed "WIFI, 17 ms, 163 Mbps" from the mock while the real link was loopback at about 1 ms.
- Fix: show the real `link.update` values. Show the encryption state only once the transport reports it (ask P1 for a contract field if needed).

**P4-4. The remote viewer accepts connections without a token, and anyone can get a token.**
- File: `agent/teleport/remote/__init__.py` (`handle_viewer`: `if token:` skips validation when no token is given; `GET /api/remote/token/{id}` has no auth).
- Symptom: any client can open `/ws/remote/{id}` without a token and, once consent is given, receive the host's screen and inject input.
- Fix: reject a missing token (close with 4401). Give the token only to the viewer device, for example by sending it over the peer link to B when consent is granted, instead of exposing it over open HTTP.

**P4-5. The pair dialog fakes success in mock mode.**
- File: `ui/src/components/pairing/PairDialog.tsx:30`.
- Symptom: pairing "succeeds" without calling `/api/pair` because mock mode is on by default (P4-1).
- Fix: always call `POST /api/pair`, and show its error text (401 wrong PIN, 429 rate limited, 502 unreachable).

## P1 notes (for reference)

- New: `core/relay.py` (P2-2 workaround), the forced loopback link for loopback-bound agents (P2-1 workaround), the `rollback` reason on every rollback, and `TELEPORT_DEV_SLOW_TRANSFER_MS` (dev/demo slow motion for transfers).
- e2e: `node scripts/py.mjs -m pytest tests/migration/e2e` starts real agents as subprocesses (about 35 s).
