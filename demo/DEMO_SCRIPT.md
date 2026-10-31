# Teleport 5-Minute Live Demo Script

> **Target Duration:** 5 Minutes (300 seconds)  
> **Audience:** Technical evaluators, distributed systems engineers, judges  
> **Core Value Proposition:** Workload mobility across heterogeneous devices with zero state loss, atomic authority handover, sub-second cutover, and seamless remote fallback when migration is infeasible.

---

## Pre-Flight Setup & URL Reference

| Service | Target URL | Description |
| :--- | :--- | :--- |
| **Projector Dashboard** | `http://localhost:5173` | Main Teleport operator cockpit (UI) |
| **Agent A (Source)** | `http://127.0.0.1:8765` | Device A (Primary Laptop / Workstation) |
| **Agent B (Target)** | `http://127.0.0.1:8766` | Device B (Secondary Node / Peer) |
| **Remote Web Viewer** | `http://localhost:5173/remote` | Low-latency canvas viewer & input pump |
| **Dev Raw Viewer** | `http://127.0.0.1:8765/api/remote/viewer` | Raw HTML/JS fallback viewer |

---

## Demo Timeline & Click-by-Click Sequence

```
[0:00 - 0:45] Stage 1: Live Mesh, Telemetry & Multi-Link Topology
[0:45 - 1:45] Stage 2: Workload Launch & Battery Depletion Trigger
[1:45 - 2:45] Stage 3: Feasibility Engine & 6/6 Atomic Checkpoint Cutover
[2:45 - 3:30] Stage 4: Fault Injection Mid-Flight & Zero-Loss Rollback
[3:30 - 4:15] Stage 5: Infeasible Workload -> Remote Access Fallback
[4:15 - 4:45] Stage 6: Audit History & Post-Mortem Step-by-Step Replay
[4:45 - 5:00] Stage 7: Invariant Summary (Single-Copy & Link Encryption)
```

---

### Stage 1: Live Mesh, Telemetry & Multi-Link Topology (0:00 - 0:45)

#### Speaker Narration
> *"Welcome. This is Teleport. Distributed workloads today are bound to the physical machine they started on. If your battery drops, your machine overheats, or you walk out of your office, your job crashes. Teleport solves this by giving workloads true physical mobility.*
> *Here on the dashboard, we see two live devices connected over our encrypted mesh: Device A, our source MacBook Pro, and Device B, our target workstation. Between them, you see our link monitor actively benchmarking latency, bandwidth, and link types (direct cable vs. WiFi). Telemetry updates every second via WebSocket."*

#### Exact Clicks & Actions
1. **Open Dashboard:** Navigate to `http://localhost:5173/` on the projector.
2. **Point to Cards:**
   - Device A card: Live CPU, memory, battery gauge (85% Charging).
   - Device B card: Hardware specs, online state.
   - Center Link card: `CABLE` badge, 1.2 ms RTT, 1000 Mbps throughput, `AES-256-GCM` encryption badge.
3. **Show Pair Dialog (Optional if already paired):**
   - Click **Pair Device** button in top bar.
   - Show PIN code verification and address entry (`127.0.0.1:8766`).
   - Click **Close**.

#### Contingency / Backup Plan
- **If Agent B is not connected:** Click the `[Mock Data]` toggle switch in the top header. The mock feeder immediately replays both devices and link statistics.

---

### Stage 2: Workload Launch & Battery Depletion Trigger (0:45 - 1:45)

#### Speaker Narration
> *"Let's launch a real data pipeline on Device A—our `pipeline_job`. It trains a token tokenizer in six explicit stages, persisting checkpoints to disk.*
> *Now, imagine Device A gets unplugged and the battery begins to plummet. Let's watch the predictive telemetry engine in action."*

#### Exact Clicks & Actions
1. **Navigate to Workloads:** Click **Workloads** in the top navigation.
2. **Inspect Manifest:** Locate `pipeline_job`. Note `runtime: python 3.11`, `6 checkpoints defined`, `remoteCapable: true`.
3. **Simulate Battery Drop:**
   - In the **Simulated Demo Control Panel** (or top controls):
   - Click the **Drain battery** button (or slide Battery to `12%` and uncheck `AC Charging`).
4. **Observe Orchestrator Alert:**
   - Within 2 seconds, an amber recommendation banner slides in:
   - `Orchestrator Recommendation: MIGRATE`
   - `Trigger: LOW_BATTERY (Predictive: 12% remaining, estimated 4 minutes to zero)`
5. **Accept Recommendation:**
   - Click **Accept & Migrate** button directly on the banner.

#### Contingency / Backup Plan
- **If agent is offline:** Navigate to `/migration?scenario=in_flight` to instantly simulate the active transfer phase.

---

### Stage 3: Feasibility Engine & 6/6 Atomic Checkpoint Cutover (1:45 - 2:45)

#### Speaker Narration
> *"Teleport never blindly migrates. Before touching a single byte, the Feasibility Engine checks CPU architecture, free RAM, disk headroom, and link quality. Every check is explained with clear reasons.*
> *Notice: the workload is still running on Device A. Authority remains strictly on Device A (Epoch 1). As checkpoints 1 through 6 stream across the encrypted link, each chunk is verified with SHA-256 integrity hashes.*
> *Only when checkpoint 6 of 6 is validated does the cutover happen. Watch the authority indicator flip to Device B (Epoch 2). Total interruption time: 42 milliseconds."*

#### Exact Clicks & Actions
1. **Observe Migration Page (`/migration`):**
   - **Feasibility Panel:** Green `MIGRATE` badge. Expand reasons:
     - `✓ Target architecture compatible (x86_64)`
     - `✓ Target RAM (19.3 GB free) exceeds minimum floor`
     - `✓ Link bandwidth (1000 Mbps, 1.2ms RTT) optimal`
   - **Phase Stepper:** Highlights `TRANSFERRING` $\rightarrow$ `VALIDATING`.
   - **Checkpoint Grid:** Watch checkpoints 1/6 $\rightarrow$ 6/6 light up green with progress bars and verified badges.
   - **Authority Indicator:** Point to `SOURCE @ Epoch 1` while sending.
   - **Cutover Event:** Stepper transitions to `FENCING` $\rightarrow$ `STARTING_TARGET` $\rightarrow$ `COMPLETED`.
   - **Authority Flip:** Badge flips to `TARGET (Device B) @ Epoch 2`.
   - **Interruption Stopwatch:** Highlights `Interruption Time: 42 ms`.

#### Contingency / Backup Plan
- **If network latency stalls transfer:** Click `Mock Feeder -> Completed Migration` or visit `/migration?scenario=completed`.

---

### Stage 4: Fault Injection Mid-Flight & Zero-Loss Rollback (2:45 - 3:30)

#### Speaker Narration
> *"What happens when the physical world betrays us? A cable gets yanked, or the target crashes mid-transfer. Traditional distributed tools leave orphan processes or corrupted split-brain state.*
> *In Teleport, authority never moves until all checkpoints are validated. Let's intentionally drop the connection during a transfer."*

#### Exact Clicks & Actions
1. **Trigger New Migration:** Click **Workloads** $\rightarrow$ Click **Migrate** on `pipeline_job`.
2. **Inject Fault:**
   - In the Demo Control Panel, click **Drop wifi** or simulate target failure.
   - Checkpoint 4 validation fails due to packet corruption.
3. **Observe Rollback:**
   - Stepper turns red: `ROLLED_BACK`.
   - Failure Reason: `Validation failed at Checkpoint 4 (SHA-256 hash mismatch: expected 9f2a..., got c83e...)`.
   - **Crucial Invariant:** Point to the Authority indicator:
     - `Authority State: SOURCE (Device A)`
     - `Workload safely resumed on Device A without state loss or corrupted files.`

#### Contingency / Backup Plan
- **Mock Fallback:** Navigate to `/migration?scenario=rollback`.

---

### Stage 5: Infeasible Workload -> Remote Access Fallback (3:30 - 4:15)

#### Speaker Narration
> *"What if migration is physically impossible? For instance, a GPU rendering workload on an ARM64 node without CUDA (`gpu_only_job`), or a legacy desktop app (`notepad_app`).*
> *Teleport's feasibility engine detects this immediately: Decision `REMOTE_ACCESS`. Instead of failing, Device B displays Device A's primary screen with interactive input injection."*

#### Exact Clicks & Actions
1. **Inspect GPU Workload:**
   - Go to **Workloads** $\rightarrow$ select `gpu_only_job`.
   - Notice requirements: `needsGpu: true`, `arch: [x86_64]`, `remoteCapable: true`.
2. **Trigger Feasibility:**
   - Click **Evaluate Feasibility** targeting Device B (`arm64-lowspec`).
   - Feasibility badge changes to purple: `REMOTE_ACCESS`.
   - Block reasons displayed:
     - `⛔ Target lacks required CUDA/GPU hardware`
     - `⛔ Architecture arm64 does not match required x86_64`
     - `✓ Workload is marked remoteCapable: fallback enabled`
3. **Launch Remote Session:**
   - Click **Start Remote Access Session**.
   - Host consent dialog appears on Device A: Click **Allow Control**.
4. **Interact with Remote Viewport (`/remote`):**
   - Live 60 FPS JPEG stream of host screen rendered on HTML5 canvas.
   - Click **Capture Controls**.
   - Type text or move mouse: input is streamed over WebSocket and injected via `pynput` with normalized scaling.
   - Click **Release Controls** / **Stop Session**.

#### Contingency / Backup Plan
- **Mock Fallback:** Navigate to `/remote?scenario=remote_access`. Click `Simulate Host Consent Modal` and test interactive controls.

---

### Stage 6: Audit History & Post-Mortem Step-by-Step Replay (4:15 - 4:45)

#### Speaker Narration
> *"Every single event, decision, checkpoint hash, and authority transition is recorded immutably in the SQLite audit log.*
> *Let's check the History page."*

#### Exact Clicks & Actions
1. **Navigate to History:** Click **History** in top navigation.
2. **Show Device Catalog:** Point out known peer devices, last seen timestamps, and the **Reconnect** prefill button.
3. **Filter Migrations:** Filter by `COMPLETED` and click **Inspect** on `mig-2026-001`.
4. **Replay Modal:**
   - Walk through the phase stepper playback.
   - Point to `Interruption Time: 42 ms` and all 10 SHA-256 checkpoint digests.
5. **Show Decision Log:** Filter by `STAY` or `REMOTE_ACCESS` to demonstrate rejected migrations where reasons were logged.

#### Contingency / Backup Plan
- History page loads `mockHistory.ts` automatically if backend SQLite is unpopulated.

---

### Stage 7: Invariant Summary (Single-Copy & Link Encryption) (4:45 - 5:00)

#### Speaker Narration
> *"To conclude, Teleport guarantees three non-negotiable distributed systems invariants:*
> 1. *Single-Copy Authority: Exactly one device holds execution authority at any epoch. Fencing prevents split-brain.*
> 2. *Atomic Rollback: If a single checkpoint fails, authority never moves, and the source continues execution unharmed.*
> 3. *Zero Overhead: Sub-second interruption times, encrypted point-to-point links, and an automatic remote fallback.*
> *Thank you. We are happy to answer any questions."*

---

## Contingency Matrix (Quick Reference)

| Failure Scenario | Live Symptom | Presenter Pivot Action |
| :--- | :--- | :--- |
| **Agent A or B fails to start** | Red disconnected badge in UI | Run `python demo/reset.py --start` or flip UI switch to `Mock Feeder: ON` |
| **WiFi router drops during presentation** | Link status says OFFLINE | Switch preferred link to Cable in `/settings` or use Mock Feeder |
| **Pynput permission denied on host OS** | Remote viewer shows screen but ignores typing | Use `notepad_app` simulated key injector or dev viewer |
| **Port conflict on 8765/8766** | `Address already in use` error | Run `python demo/reset.py` in terminal |
| **Projector resolution clipping** | Small UI text or horizontal scroll | Press `Ctrl + -` (zoom 90%) or use Teleport's built-in high-contrast projector mode |

