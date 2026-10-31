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
- P1 workaround: `core/relay.py` (removed in Integration 2 after P2 fixed this).

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

---

# Integration 2: two real laptops (2026-11-01)

Found while writing [RUNBOOK.md](RUNBOOK.md) and running [TEST_MATRIX.md](TEST_MATRIX.md) on main
(P2 prompt 5, P3 orchestrator and history, P4 dashboard). Each section can be pasted into that owner's next prompt.

## Status of Integration 1 issues

| Fixed | Still open |
| --- | --- |
| P2-1 (loopback-bound agents advertise loopback only), P2-2 (peer.stats), P2-3 (PIN only for local callers), P2-4 (real AES-256-GCM session), P2-6, P2-7 (`local_info` cached), P3-1, P3-4, P3-5, P4-3, P4-4 | P2-5 (manifest signing), P3-2 (strict typing, see P3-9), P3-3 (lint, see P3-10), P4-1, P4-2 (partly), P4-5 |

P1 removed its workarounds for P2-1 (forced loopback link) and P2-2 (`core/relay.py`). The
forced-loopback workaround was also what made P2's `test_failover_cable_to_wifi` fail.

## P2: devices, transport, security

**P2-5 (still open). The peer link does not sign migration manifests.**
- `mig.prepare` still uses P1's SHA-256 fallback (`migration/manager.py` `DigestSigner`), which checks integrity, not authenticity. `security/manifest.py` has `sign_manifest`/`verify_manifest`, but `PeerLinkService` does not expose them.
- Fix: add `sign_manifest(payload: bytes) -> str` (identity key) and `verify_manifest(device_id, payload, signature) -> bool` (the peer key stored at pairing) to `PeerLinkService`. Migration picks them up automatically. Matrix row S3.

**P2-8. With full packet loss the link flaps instead of staying down.**
- Files: `agent/teleport/transport/service.py` (reconnect loop), `connection.py` / `quality.py` (quality of a fresh connection).
- Symptom: with `POST /api/dev/fault-inject {"peerId": B, "dropRate": 1.0}`, A publishes `device.lost` about every 3 s and reconnects. Each new connection reports one `link.update` with `lossPct 0, mbps 5000` between the 100%-loss samples, so nothing sees a sustained outage.
- Repro: `tests/migration/e2e/test_matrix.py::test_t3_lost_connectivity_is_detected_and_recommended` (currently a strict xfail), or pair two agents, inject `dropRate 1.0` and watch `link.update` on A's `/ws/events`.
- Fix: carry the loss estimate over a reconnect for the same peer (or do not report quality before the first ping round trip), and back off reconnects while the fault is active.

**P2-9. A MacBook's Wi-Fi (`en0`) is advertised as cable.**
- Files: `agent/teleport/devices/capabilities.py` (`guess_link_type`) versus `agent/teleport/transport/link_detector.py` (`classify_interface`).
- Symptom: `guess_link_type("en0", "192.168.1.5")` gives `cable`, while `classify_interface("en0", ...)` gives `wifi`. The address is advertised as cable, preferred, and the dashboard shows CABLE over wifi.
- Fix: use one classifier (`classify_interface`, with the interface speed) in both places.

**P2-10. Virtual adapters are advertised as cable and preferred over Wi-Fi.**
- File: `agent/teleport/devices/capabilities.py` (`get_network_addresses`; `guess_link_type` falls back to cable).
- Symptom: with `--host 0.0.0.0` this laptop advertises `192.168.56.1` (VirtualBox Host-Only) and `172.27.64.1` (`vEthernet (WSL)`) as cable, ahead of Wi-Fi. The peer dials them first (timeouts). If both laptops have VirtualBox, `192.168.56.1` can be the dialer's **own** adapter, so it connects to itself.
- Repro: `python -c "from teleport.devices.capabilities import guess_link_type as g; print(g('VirtualBox Host-Only Network','192.168.56.1'), g('vEthernet (WSL)','172.27.64.1'))"` prints `cable cable`.
- Fix: skip virtual adapters (VirtualBox, VMware, vEthernet, Hyper-V, WSL, docker, br-, veth, utun, tailscale, ZeroTier), or give unknown adapters the lowest priority instead of cable. Never advertise or dial an address the dialer owns itself.
- Runbook workaround: bind each agent to one IP (`--host <ip>`).

**P2-11. The receiving side labels every inbound link "cable".**
- File: `agent/teleport/transport/service.py:263` calls `classify_interface(name="peer-in", ip=client_host)`. The name is a constant, so the fallback is always cable.
- Symptom: on wifi, B's dashboard, link-quality and target-side migration status say cable.
- Fix: find the local interface that owns the socket's local address (`ws.scope["server"][0]`, matched with `psutil.net_if_addrs()`) and classify that interface, or take the link type from the dialer's hello.

**P2-12. The pairing PIN cannot be read on a laptop bound to its LAN IP.**
- Files: `agent/teleport/transport/service.py` (`get_pair_info` serves the PIN only to `127.0.0.1`), `pairing.py` (the initial PIN is never logged).
- Symptom: with `--host 192.168.x.y` nothing listens on 127.0.0.1, and B's own request to `http://192.168.x.y:8765/api/pair` comes from 192.168.x.y, so no PIN is shown. B's dashboard has no PIN either. Pairing on two laptops only works with `TELEPORT_DEV_PIN`.
- Fix: also treat the agent's own bound IPs (any address of this machine, `psutil.net_if_addrs()`) as local, and log the initial PIN at startup like a rotated one.

## P3: feasibility, orchestration, history

**P3-6. Triggers on a peer's stats act on this device's workloads.**
- File: `agent/teleport/orchestration/service.py` (`process_stats` handles every `stats.update`, and peers' stats are now forwarded onto the bus; `_trigger_fired` ignores `device_id` in `_get_running_workloads`).
- Symptom: B's battery drops to 5%, and A's orchestrator fires `low_battery` for B and recommends (in auto mode, starts) moving **A's** workload, with B, the device with the low battery, as the target.
- Repro: `tests/migration/e2e/test_matrix.py::test_t1c_peer_low_battery_does_not_move_local_workloads` (strict xfail; it starts failing with XPASS once fixed, so remove the marker then).
- Fix: evaluate resource triggers only for `stats.deviceId == ctx.device_id`. Use peers' stats only to rank targets and to refuse a low-battery target.

**P3-7. Lost connectivity is never detected.**
- File: `agent/teleport/orchestration/service.py` (`process_link` needs 3 s of unbroken 100% loss, and `device.lost` is not handled).
- Symptom: a dead link never produces a `connectivity_lost` recommendation, because of P2-8's flapping and no `DeviceLostEvent` handling. Also define what the trigger should do: the lost peer cannot be the migration target.
- Repro: `test_matrix.py::test_t3_lost_connectivity_is_detected_and_recommended` (strict xfail).
- Fix: subscribe to `DeviceLostEvent` (lost immediately). Count the 3 s window over samples without resetting on one good sample. When the **local** device loses connectivity, recommend the best reachable peer. Never target the lost peer.

**P3-8. `tests/history/test_history_revisit.py` does not import, so it never runs.**
- Symptom: `ImportError: cannot import name 'CheckpointUnit' from 'contract.contract'`. Before P1 added `--continue-on-collection-errors` to `pytest.ini`, this aborted the whole `npm test` run (0 tests ran).
- It also uses `phase="ABORTED"`, which is not a contract Phase, and plain strings for `DeviceAddr`, `trigger` and `link`.
- Fix: use the contract types (`CheckpointRecord`, real phases). If `CheckpointUnit` or `ABORTED` are needed, request the contract change from P1.

**P3-9. mypy strict errors in P3 files (part of the 51 errors in `npm run typecheck`).**
- `agent/teleport/history/router.py` (19): it calls `list_device_summaries`, `get_device_detail`, `get_migration`, `export_history` and `list_migrations(device=, workload=, decision=)` on `ctx.history`, typed as the contract's `HistoryStore` Protocol. Either `cast` to `SqliteHistoryStore` in the router, or ask P1 to add those methods to the Protocol.
- `history/store.py:553`, `feasibility/explain.py:46` (`.value` on a Literal string), `orchestration/service.py:229` (tuple typed `str` instead of `Trigger`), `dev/orchestration/replay.py:43` and `tests/orchestration/test_orchestrator.py:54` (a method named `list` used as a type: use `builtins.list`), `dev/feasibility/cli.py:50`, `tests/feasibility/fixtures/__init__.py:18,22`, `tests/feasibility/test_engine.py:173-175` (`dict` without type arguments).
- P1 removed the temporary mypy exclusions for these files (P3-1 is fixed), so they are now checked.

**P3-10. `npm run lint`: 7 ruff errors, all in P3 files.**
- `agent/teleport/feasibility/explain.py:13` (unused import `Decision`), plus unsorted imports in `dev/feasibility/cli.py`, `dev/orchestration/replay.py`, `tests/feasibility/test_checks.py`, `tests/feasibility/test_engine.py`, `tests/history/test_history.py`, `tests/orchestration/test_orchestrator.py`.
- Fix: `node scripts/py.mjs -m ruff check --fix agent/teleport/feasibility agent/teleport/orchestration agent/teleport/history dev/feasibility dev/orchestration tests/feasibility tests/orchestration tests/history`.

**P3-11. `build_history_router` is never mounted.**
- File: `agent/teleport/history/__init__.py` exports `build_history_router`, but nothing includes it, so `/api/history/devices/{id}`, `/migrations/{id}`, `/export` and the filters return 404.
- Fix: in `SqliteHistoryStore.__init__`, set `self.router = build_history_router(ctx)`. The app mounts a service's `router` automatically. P1 changed `core/api.py` so its minimal contract `/api/history/*` routes step aside when the history store has a router. Keep `GET /api/history/devices|migrations|decisions` returning the contract types (`DeviceInfo[]`, `MigrationStatus[]`, `DecisionLog[]`), or tell P4 and P1 first.

## P4: dashboard, remote

**P4-1 (still open). The dashboard starts in mock mode and shows mock devices with a live agent.**
- Symptom on `npm run dev:two` with paired agents and a completed migration: device cards "MacBook Pro M2" / "Workstation Tower", "Active Devices: 4", and after any reload the mock feeder is on again. Matrix rows U1, A2.
- Fix: as in Integration 1 (start with mock off, turn it on only when `/api/health` fails, take `thisDeviceId` from `/api/health`).

**P4-6. Migration and authority state are not loaded on page load.**
- Files: `ui/src/api.ts` (no `GET /api/migrations`), `ui/src/store/reducer.ts` (`authority` only from live `authority.change`).
- Symptom: with the Migration page open during a migration it is correct ("Lease Epoch 2", source RELEASED, target TARGET). After a reload it shows the mock "TRANSFERRING, Epoch 1" while the real migration is COMPLETED at epoch 2.
- Fix: on load, fetch `GET /api/migrations` (latest status per workload, with `authority` and `metrics`) and `GET /api/workloads/runs`. Then apply `migration.status` and `authority.change` events.

**P4-7. The Remote page shows a fake stream.**
- File: `ui/src/pages/RemotePage.tsx:17` (`useState<number>(18.4)`) and the streaming flag.
- Symptom: with no remote session at all it shows "STREAMING ACTIVE, FPS 18.4, 1280 x 720".
- Fix: show "No session" until `GET /api/remote/sessions` or a `remote.session` event gives a session. Take the FPS from the frames actually received.

**P4-8. The UI end-to-end tests only work on mock data.**
- File: `tests/ui/e2e/smoke.spec.ts`.
- Symptom: `npm run e2e` passes 7/7 without an agent, but 5/7 with a live agent on :8765 ("dashboard loads live device stats on mock data", "scenario 5: history page"), because they assert mock ids (`device-card-device-b`, `btn-reconnect-device-b`).
- Fix: run these against a mocked API (Playwright `page.route('/api/**')`), or add a live variant that starts `npm run dev:two` and asserts the real device names.

**P4-9. mypy errors in `examples/`.**
- `examples/pipeline_job/main.py` (9), `examples/gpu_only_job/main.py` (3), `examples/notepad_app/main.py` (2): `teleport_sdk = None` fallbacks typed as Module, and `restore()` results (`dict | bytes | None`) assigned without narrowing.
- Fix: `import teleport_sdk` unconditionally (the runner puts `sdk/` on `PYTHONPATH`), and check `isinstance(state, dict)` after `restore()`.

**P4-10. New contract fields are not shown yet.**
- `authority.conflict` events (split-brain guard) and `MigrationStatus.metrics` (per-checkpoint time and Mbps, skipped units, link, interruption). The Migration and History pages should show both.

## P1 (own items, for the record)

- Done this round: removed the P2-1/P2-2 workarounds, `--continue-on-collection-errors`, history routes defer to a history router, split-brain conflicts are now reported on both sides (`auth.leases.conflicts`), new automated rows (STAY, triggers, history, encryption, feasibility budget).
- Not done: the two-laptop rows (L4, L5) need the hardware. Run RUNBOOK §6 and §7 and fill them in.

## Follow-up (P1, after P2/P4 reports): contract fields and settings

**Contract (done, P2 request).** `LinkQuality` has `online?: boolean; simulated?: boolean`, and `Stats` has
`stale?: boolean`, in both `contract.ts` and `contract.py`. All three are optional: omitted when not set.

**Settings (done, P4 report).** `GET/PUT /api/settings` now persist `predictionWindowSec` (5 to 3600),
`preferredLink` (`auto | cable | wifi`) and `remoteConsent` (`prompt | auto_allow | deny_all`) in
`prefs.json`. Unknown fields now return **422** instead of being dropped silently. `checkpointChunkKb` is
accepted as a deprecated alias of `chunkSizeKb`, clamped to 16 to 512 KB, and echoed in GET.

- **P2:** drop `ExtendedLinkQuality` (`transport/quality.py`) and `ExtendedStats` (`devices/service.py`), and use
  the contract models with `online=`, `simulated=` and `stale=`. Note: unset now means *omitted* instead of
  `online: true` / `stale: false`, so set them explicitly where it matters. `preferredLink` is applied through
  `set_forced_link()` by core (at startup and on every PUT; `auto` keeps `TELEPORT_FORCE_LINK`). Also seen
  once under heavy load, without fault injection: a spurious `device.lost` mid-migration (rolled back
  safely). Probably the same root cause as P2-8.
- **P3:** read `ctx.prefs.predictionWindowSec` in the battery predictor instead of a constant.
- **P4:** use `chunkSizeKb` (max 512, because each chunk travels base64 in one peer frame) instead of
  `checkpointChunkKb` (default 1024 is above the limit), then P1 removes the alias. The remote service should
  read `ctx.prefs.remoteConsent`: `auto_allow` grants consent, `deny_all` refuses `start_session`, `prompt`
  keeps today's consent dialog.

## Hardening (P1, 2026-11-01)

**P2-13. Transfer throughput is capped near 80 Mbps by the frame encoding, not by the link.**
- File: `agent/teleport/transport/connection.py` (`send`): each `MigChunk` is JSON with the chunk
  base64'd inside (`dataB64`), then AES-GCM encrypted, then base64'd again into a **text** WebSocket frame.
  That is about 1.8x the bytes, two base64 passes and one big JSON per 256 KB chunk.
- Measured: `node scripts/py.mjs scripts/bench_transfer.py` gives about 80 Mbps on loopback at every chunk
  size of 256 KB or more, CPU-bound.
- Fix: send encrypted frames as **binary** WebSocket messages (no outer base64). Optionally, a binary
  chunk frame (header + raw bytes) would also drop the inner base64. That one is a contract change, so ask P1.
- Also seen under heavy load: a spurious `device.lost` with the peer still alive. P1 now reconnects
  once (5 s) before acting on it, so migrations no longer roll back on a blip, but the transport
  should not emit it while the peer answers.
