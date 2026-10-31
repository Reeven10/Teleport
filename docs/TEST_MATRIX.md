# Teleport test matrix

Run 2026-11-01 on `feat/core` (updated after hardening) after merging main (P2 transport/security prompt 5, P3 orchestrator
and history, P4 dashboard and remote). One Windows laptop: real agents as subprocesses or in-process,
on loopback. The two-laptop rows are **manual** and follow [RUNBOOK.md](RUNBOOK.md).

**Automated result: 347 passed, 0 failed, 2 expected failures (known bugs, `xfail(strict=True)`), 1
collection error (P3 test file).** End to end with real agents: 11/11 passed + the 2 expected failures.
Failure injection: 16/16. UI: Vitest 19/19, Playwright 7/7 on mock data (5/7 with a live agent).
Issue ids (P2-x, P3-x, P4-x) are in [INTEGRATION_ISSUES.md](INTEGRATION_ISSUES.md).

Commands: `npm test` (all pytest), `node scripts/py.mjs -m pytest tests/migration/e2e` (real agents,
about 3 min), `npm run test:ui`, `npm run e2e`, `npm run typecheck`, `npm run lint`.

## Feasibility decisions

| ID | Case | How | Test / what to check | Result |
| --- | --- | --- | --- | --- |
| F1 | MIGRATE: compatible target | auto | `tests/migration/e2e/test_scenarios.py::test_2_migrate_counter_job_to_b`; P3 unit `tests/feasibility/test_engine.py` | PASS |
| F2 | REMOTE_ACCESS: arch blocked, workload remote-capable | auto | `test_scenarios.py::test_3_incompatible_target_means_remote_access` | PASS |
| F3 | STAY: needs a GPU, not remote-capable | auto | `tests/migration/e2e/test_matrix.py::test_f3_stay_when_neither_migration_nor_remote_works` | PASS |
| F4 | Every rule (arch, OS, runtime, libs, RAM x1.2, CPU, disk, GPU, battery, online, link) | auto | `tests/feasibility/test_checks.py` (95), `test_engine.py`, `test_explain.py` | PASS |
| F5 | Feasibility < 500 ms | auto | `tests/core/test_budgets.py::test_f5_feasibility_result_within_500ms` (real engine, 5 runs) | PASS |

## Links

| ID | Case | How | Test / what to check | Result |
| --- | --- | --- | --- | --- |
| L1 | Loopback (`dev:two`) | auto | all `tests/migration/e2e` (status `link: "loopback"`) | PASS |
| L2 | Interface classification (wifi, cable, USB tethering, link-local) | auto | `tests/transport/test_link_detector.py` | PASS |
| L3 | Cable preferred, failover cable to wifi, forced link | auto | `tests/transport/test_link_quality.py::test_failover_cable_to_wifi` | PASS |
| L4 | Wifi between two laptops | manual | RUNBOOK §6: pair over wifi IPs, `GET /api/transport/link-quality` on A shows `"link": "wifi"`, migration `link: "wifi"` | NOT RUN (needs 2 laptops). Known: B labels the inbound link cable (P2-11), Mac en0 shows cable (P2-9) |
| L5 | Data cable (direct ethernet / USB) between two laptops | manual | RUNBOOK §7: cable IP on both, `ping`, link-quality shows `"link": "cable"`, dashboard card CABLE, higher Mbps in metrics | NOT RUN (needs 2 laptops). Bind with `--host <cable IP>` (P2-10) |

## Triggers

| ID | Case | How | Test / what to check | Result |
| --- | --- | --- | --- | --- |
| T1 | Low battery, auto mode: migrates by itself | auto | `test_matrix.py::test_t1_low_battery_auto_mode_migrates` | PASS |
| T1b | Low battery, recommend mode: recommendation only | auto | `test_matrix.py::test_t1b_low_battery_recommend_mode_only_recommends` | PASS |
| T1c | A peer's low battery must not move this device's workload | auto | `test_matrix.py::test_t1c_peer_low_battery_does_not_move_local_workloads` (xfail strict) | **FAIL** (P3-6) |
| T2 | CPU pressure (>= 90% for 20 s) | auto | `test_matrix.py::test_t2_cpu_pressure_recommends_after_sustained_load` | PASS |
| T3 | Lost connectivity | auto | `test_matrix.py::test_t3_lost_connectivity_is_detected_and_recommended` (xfail strict) | **FAIL** (P2-8, P3-7) |
| T4 | User command | auto | `test_scenarios.py::test_2_migrate_counter_job_to_b` (trigger `user_command`) | PASS |
| T5 | Memory pressure, prediction, cooldown, hysteresis | auto | `tests/orchestration/test_orchestrator.py` (11) | PASS |

## Migration, rollback, authority

| ID | Case | How | Test / what to check | Result |
| --- | --- | --- | --- | --- |
| M1 | 6 checkpoints, hash-validated, resumes on B, A gone, interruption reported | auto | `test_scenarios.py::test_2_migrate_counter_job_to_b`, `tests/migration/test_migration.py` | PASS (183 to 193 ms, real agents, 4 hops) |
| M3 | Interruption < 3 s, freeze window carries only changes | auto + bench | `test_faults.py::test_slow_link_completes_and_reports_a_small_freeze`; `scripts/bench_transfer.py` (20 MB unit: 53 to 59 ms) | PASS |
| M2 | Migrate back and repeatedly, delta only, epoch rises | auto | `tests/migration/test_continuity.py::test_migrate_there_and_back_twice_resends_only_changes` | PASS |
| RB1 | Target killed mid-transfer: ROLLED_BACK, A keeps running, reason shown | auto | `test_scenarios.py::test_4_target_killed_mid_transfer_rolls_back` | PASS |
| RB2 | Corrupt chunk, start failure, link cut, abort, stale epoch, 5 of 10 | auto | `tests/migration/test_migration.py` (14) | PASS |
| RB3 | Agent restart in every phase, never two copies | auto | `tests/migration/test_continuity.py` (restart tests) | PASS |
| A1 | Split brain: lower epoch stops, conflict reported on both sides | auto | `test_continuity.py::test_split_brain_lower_epoch_stops_and_conflict_is_reported` | PASS |
| A2 | Authority status in the dashboard | manual | `npm run dev:two`, Migration page open, migrate B to A: shows "Lease Epoch 2", source RELEASED, target TARGET. Then reload the page | **FAIL** after reload: mock data shows "TRANSFERRING, Epoch 1" (P4-1, P4-6). PASS live while the page is open |
| A3 | authority.change on /ws/events | auto | `test_scenarios.py::test_2_migrate_counter_job_to_b` | PASS |

## Failure injection (hardening)

Every row must end COMPLETED or ROLLED_BACK, with a short dashboard message, and never two running copies.

| ID | Fault | Test (`tests/migration/test_faults.py`) | Result |
| --- | --- | --- | --- |
| FI1 | Link killed in each phase: CONNECTING, EVALUATING, TRANSFERRING, VALIDATING, FENCING, STARTING_TARGET | `test_link_killed_in_every_phase[*]` (6) | PASS (ROLLED_BACK; STARTING_TARGET waits for the lease, then rolls back) |
| FI2 | Link killed right after the target started (mig.started lost) | `test_link_killed_right_after_target_started` | PASS (COMPLETED via the target's lease) |
| FI3 | Corrupt chunk once / persistently | `test_corrupt_chunk_once_is_detected_and_resent`, `test_persistently_corrupt_chunk_rolls_back` | PASS |
| FI4 | Target killed while it starts | `test_target_killed_while_starting` | PASS |
| FI5 | Source killed during the fence | `test_source_killed_during_fence` | PASS |
| FI6 | Slow link (5 ms per message, 300 KB unit, 32 KB chunks) | `test_slow_link_completes_and_reports_a_small_freeze` | PASS |
| FI7 | Target disk too small (refused up front) / full mid-transfer (ENOSPC) | `test_target_disk_too_small_is_refused_up_front`, `test_target_disk_full_mid_transfer_aborts` | PASS |
| FI8 | Workload exits during the transfer | `test_workload_exits_during_transfer` | PASS |
| FI9 | Target unreachable from the start | `test_unreachable_target_is_a_clear_rollback` | PASS |
| FI10 | Restart in every phase, split brain, there and back | `tests/migration/test_continuity.py` (19) | PASS |
| FI11 | Short human-readable messages | `assert_clear_outcome` in every FI test (10 to 160 chars, a sentence, no traces or ids) | PASS |

## History, reasons, security

| ID | Case | How | Test / what to check | Result |
| --- | --- | --- | --- | --- |
| H1 | Devices, migrations, decisions saved; survive an agent restart | auto | `test_matrix.py::test_h1_history_is_saved_and_survives_restart` | PASS |
| H2 | History page shows real data | manual | dev:two, History page after a migration: "1 Migrations Logged", real ids | PASS |
| H4 | P3's full history API mounted (`/api/history/devices/{id}`, `/migrations/{id}`, `/export`, filters) | auto | `tests/core/test_app.py::test_history_module_router_is_mounted` | PASS |
| H3 | History store unit tests | auto | `tests/history/test_history.py` (7); `test_history_revisit.py` | PASS (7); **ERROR** revisit file does not import (P3-8) |
| R1 | Reasons for every decision (severity, code, sentence) | auto | `assert_reasons` in F3, T1, T1b, T2 and over all of `/api/history/decisions` in H1; rollback reason in RB1 | PASS |
| R2 | Reasons visible in the dashboard | manual | Migration and History pages list the reasons of the last decision | NOT CHECKED in detail (P4 pages show mock data first, P4-1) |
| S1 | No plaintext state in captured peer frames | auto | `tests/migration/e2e/test_encryption.py` records every WebSocket frame both agents send during a real migration; checks raw and base64-decoded frames; only the key exchange is JSON | PASS |
| S2 | Session crypto, identity, manifest signing helpers, tokens | auto | `tests/security/*` (15) | PASS |
| S3 | Migration manifest signed with the device key | auto/manual | `mig.prepare` still uses the SHA-256 fallback (`DigestSigner`) | **FAIL** (P2-5) |
| S4 | PIN only for the local user; usable on two laptops | manual | RUNBOOK §5 with `--host <LAN IP>` | **FAIL**: the PIN cannot be read when bound to a LAN IP (P2-12). Workaround `TELEPORT_DEV_PIN` |
| S5 | Remote access needs consent and a token | auto | `tests/remote/test_consent_and_tokens.py` | PASS |

## Dashboard and code health

| ID | Case | How | Test / what to check | Result |
| --- | --- | --- | --- | --- |
| U1 | Dashboard shows the real paired devices and live stats | manual | dev:two, Dashboard page | **FAIL**: mock devices "MacBook Pro M2" and "Workstation Tower" (P4-1) |
| U2 | Remote view with a real session | manual | Remote page without any session | **FAIL**: shows "STREAMING ACTIVE, 18.4 FPS" with no session (P4-7) |
| U3 | UI unit tests | auto | `npm run test:ui` | PASS (19/19) |
| U4 | UI end to end | auto | `npm run e2e` | PASS 7/7 without an agent; 5/7 with a live agent (P4-8) |
| Q1 | `npm run typecheck` | auto | mypy strict + tsc | **FAIL**: 32 mypy errors in 12 P3/P4 files (P3-9, P4-9); P1 files and tsc clean. The history router's 19 are gone (Protocol extended) |
| Q2 | `npm run lint` | auto | ruff + eslint | **FAIL**: 7 ruff errors, all in P3 files (P3-10); P1 files and eslint clean |
| C1 | Settings from the dashboard persist (`predictionWindowSec`, `preferredLink`, `remoteConsent`, `checkpointChunkKb` alias), typos rejected | auto | `tests/core/test_app.py::test_dashboard_settings_persist_and_apply` | PASS |
| C2 | Contract flags `LinkQuality.online/simulated`, `Stats.stale` | auto | `tests/core/test_contract.py::test_link_quality_and_stats_optional_flags` | PASS |
