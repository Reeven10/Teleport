# Teleport Multi-Laptop Team Run Guide

This guide details the operational procedures, physical setup, command sequences, and network configuration for running a live multi-machine demonstration of Teleport across two laptops and a presentation projector.

---

## 1. Machine Roles & Responsibilities

```
+---------------------------------------------------------------------------------+
|                                 PHYSICAL TOPOLOGY                               |
|                                                                                 |
|   +-----------------------+                         +-----------------------+   |
|   |   LAPTOP 1 (Host A)   | <=== Gigabit Cable ===> |   LAPTOP 2 (Peer B)   |   |
|   |  - Teleport Agent A   |        Direct LAN       |  - Teleport Agent B   |   |
|   |  - Source Workloads   |                         |  - Target Workloads   |   |
|   |  - IP: 192.168.1.101  | <--- WiFi (Backup) ---> |  - IP: 192.168.1.102  |   |
|   +-----------------------+                         +-----------------------+   |
|               |                                                                 |
|          HDMI / USB-C                                                           |
|               v                                                                 |
|   +-----------------------+                                                     |
|   |  PROJECTOR / DISPLAY  |                                                     |
|   |  - React Dashboard    |                                                     |
|   |  - URL: :5173         |                                                     |
|   +-----------------------+                                                     |
+---------------------------------------------------------------------------------+
```

### Team Roster
- **Presenter / Driver (Laptop 1):** Delivers verbal pitch, navigates UI on projector, triggers migration and fault injection scenarios.
- **Operator (Laptop 2):** Monitors Agent B logs, handles manual link disconnection/reconnection (cable pull), and validates target process execution.

---

## 2. Hardware & Network Setup

### Physical Connections
1. **Ethernet Direct Link (Primary):**
   - Connect an Ethernet cable directly between Laptop 1 and Laptop 2 (or via a gigabit switch).
   - Set static IPs or allow link-local self-assignment:
     - **Laptop 1:** `192.168.1.101/24`
     - **Laptop 2:** `192.168.1.102/24`
2. **WiFi Network (Secondary / Fallback):**
   - Connect both laptops to the venue WiFi or a mobile hotspot as a backup link.
3. **Display Output:**
   - Connect Laptop 1 HDMI/USB-C to the projector or stage monitor (Resolution: 1080p, 60Hz).

---

## 3. Pre-Flight Staging Checklist

Execute these verification checks **15 minutes before showtime**:

- [ ] **Python Version:** Verify Python 3.11+ is active on both laptops: `python --version`
- [ ] **Node Version:** Verify Node 20+ on Laptop 1: `node --version`
- [ ] **Dependencies:**
  - `uv pip install -e .` on both laptops
  - `npm install` on Laptop 1
- [ ] **Firewall / Port Permissions:** Ensure incoming TCP ports `8765`, `8766`, and `5173` are unblocked.
- [ ] **Clean Slate:** Run the reset script on both machines:
  ```bash
  python demo/reset.py
  ```
- [ ] **Projector Resolution Check:**
  - Open `http://localhost:5173` on Laptop 1 and drag browser window to projector display.
  - Press `F11` (Full Screen) in Chrome/Firefox.
  - Verify cards and text are clearly legible from 15 feet away.

---

## 4. Startup & Execution Order

### Step 1: Laptop 2 (Peer / Target Device B)
Launch Agent B on Laptop 2 first:
```bash
# In Claudes-Angels_Final-Round root:
python -m teleport --port 8766 --home .teleport-dev/b --sim-profile arm64-lowspec --name "Device B"
```
*Verify output: `[teleport] Agent started listening on 0.0.0.0:8766`*

---

### Step 2: Laptop 1 (Host / Source Device A & UI)
Launch Agent A and the UI cockpit on Laptop 1:

**Terminal 1 (Agent A):**
```bash
python -m teleport --port 8765 --home .teleport-dev/a --sim-profile default --name "Device A"
```

**Terminal 2 (Dashboard UI):**
```bash
npm run dev:ui
```
*UI will be available at `http://localhost:5173`*

---

### Step 3: Single-Laptop Fallback (Both Agents on Laptop 1)
If Laptop 2 is unavailable or running off a single presentation laptop, launch the entire stack with a single command:
```bash
npm run dev:two
```
This concurrently boots:
- Agent A on `http://127.0.0.1:8765`
- Agent B on `http://127.0.0.1:8766`
- React Vite Dashboard on `http://localhost:5173`

---

## 5. Pairing the Devices

1. On the Dashboard (`http://localhost:5173`), click **Pair Device** in the top navigation bar.
2. In the modal:
   - **Target Address:** Enter `192.168.1.102:8766` (or `127.0.0.1:8766` if running local `dev:two`).
   - **PIN:** Enter `123456` (or the PIN displayed in Agent B's terminal startup banner).
   - Click **Connect & Pair**.
3. Upon success, Device B's card lights up on the dashboard and the center link card indicates active link quality metrics.

---

## 6. Live Presentation Run Steps

Follow the scripted stages in [demo/DEMO_SCRIPT.md](file:///c:/Users/menez/bnb_final/Claudes-Angels_Final-Round/demo/DEMO_SCRIPT.md):

1. **Dashboard Overview:** Point out live metrics, AES-256 encrypted link, and CPU/RAM/Battery meters.
2. **Launch `pipeline_job`:** Navigate to Workloads $\rightarrow$ start the token trainer.
3. **Inject Battery Drain:** Click **Drain battery** in the Demo Control Panel $\rightarrow$ Accept the recommendation.
4. **Inspect Migration:** Show checkpoint progress (1/6 to 6/6), source authority holding until validated, and sub-50ms cutover.
5. **Demonstrate Rollback:** Trigger a secondary migration and click **Drop wifi** or simulate validation failure $\rightarrow$ show zero state loss on Source.
6. **Remote Access Fallback:** Evaluate `gpu_only_job` or `notepad_app` $\rightarrow$ feasibility returns `REMOTE_ACCESS` $\rightarrow$ launch interactive remote viewport.
7. **Audit Trail:** Review historical logs and post-mortem replay on `/history`.

---

## 7. Emergency Reset & Troubleshooting

### Problem: Agent Port Conflict (`Address already in use`)
```bash
python demo/reset.py
```
This forces termination of all lingering processes on ports 8765, 8766, and 5173, and wipes `.teleport-dev/`.

### Problem: Live Agent Offline / Network Disconnected during Presentation
- Toggle the **Mock Feeder** switch in the top header.
- The UI immediately swaps to client-side simulated data streams with full interactive fidelity, allowing the presentation to continue uninterrupted without the audience noticing backend networking drops.

