# Teleport demo runbook: two real laptops

Laptop **A** runs the workload and is the source. Laptop **B** is the target. Commands are shown for
Windows PowerShell and macOS/Linux. The agent uses **one TCP port, 8765**, for everything: REST,
`/ws/events`, the dashboard (`http://<ip>:8765/`) and the encrypted peer link (`/peer`).

Rehearse once on one laptop first with `npm run dev:two` (A on :8765, B on :8766, UI on :5173).

## 1. Install (both laptops)

Needs Python 3.11+, Node 20+ and git.

```bash
git clone <repo-url> teleport
cd teleport
python -m venv .venv
```

Activate the venv: `.venv\Scripts\activate` (Windows) or `source .venv/bin/activate` (macOS/Linux).

```bash
pip install -e agent
npm install
npm run build
```

`npm run build` puts the dashboard in `ui/dist`, so the agent serves it at `http://<ip>:8765/`.
Check it works: `node scripts/py.mjs -m pytest tests/core -q` should pass.

## 2. Firewall: allow TCP 8765 inbound (both laptops)

- **Windows** (PowerShell as Administrator):
  ```powershell
  New-NetFirewallRule -DisplayName "Teleport 8765" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow -Profile Any
  ```
  The wifi profile is often "Public". `-Profile Any` covers it. If Windows pops up a "Python" dialog
  on the first start, tick both Private and Public.
- **macOS**: System Settings > Network > Firewall > Options, allow incoming connections for the
  venv's `python3`. Or turn the firewall off for the demo.
- **Linux**: `sudo ufw allow 8765/tcp` (if ufw is active).

Check from the **other** laptop once the agent runs (step 4):

```powershell
Test-NetConnection <other-ip> -Port 8765          # Windows: TcpTestSucceeded : True
```

```bash
nc -vz <other-ip> 8765                            # macOS/Linux: succeeded / open
```

## 3. Find each laptop's IP on the network you want to use

| OS | Wifi | Cable |
| --- | --- | --- |
| Windows | `ipconfig`, section "Wireless LAN adapter Wi-Fi", IPv4 Address | `ipconfig`, section "Ethernet adapter Ethernet" (or the USB adapter's name) |
| macOS | `ipconfig getifaddr en0` | `ifconfig` for the USB/Thunderbolt adapter (`en5`, `en7`, ...; "Thunderbolt Bridge" is `bridge0`) |
| Linux | `ip -4 addr show wlan0` (or `wlp*`) | `ip -4 addr show eth0` (or `enp*`, `enx*`, `usb0`) |

Write both IPs down: **A_IP** and **B_IP**.

**Important: bind each agent to that one IP** (`--host <ip>`, below). The agent then advertises
only that address, so the peer link uses exactly the network you chose. Without it (`--host 0.0.0.0`)
the agent advertises every adapter, including VirtualBox, WSL and Hyper-V virtual adapters, and
labels them "cable" (issues P2-9 and P2-10). The peer may then dial a virtual adapter first, or even itself.

## 4. Start the agents

Use the same command on each laptop with its own IP and name. **Set `TELEPORT_DEV_PIN`**: an agent bound
to a LAN IP cannot show its random PIN, because the PIN is only served to loopback callers and the
initial PIN is not logged (P2-12). Pick any 6 digits.

```powershell
# Windows, laptop A (use B_IP and "Laptop B" on B)
$env:TELEPORT_DEV_PIN = "246810"
python -m teleport --host <A_IP> --port 8765 --home $HOME\.teleport-demo --name "Laptop A"
```

```bash
# macOS/Linux, laptop A
TELEPORT_DEV_PIN=246810 python -m teleport --host <A_IP> --port 8765 --home ~/.teleport-demo --name "Laptop A"
```

- Real hardware stats are used. Add `--sim-profile default` on A and `--sim-profile arm64-lowspec` on
  B only if you want the simulated, SIMULATED-labeled devices for scenario 3.
- Open the dashboard: `http://<A_IP>:8765/` on A and `http://<B_IP>:8765/` on B.
- Health: `curl http://<A_IP>:8765/api/health` should return `"ok": true` and the device id.

## 5. Pair (once)

1. The PIN is B's `TELEPORT_DEV_PIN`. With `dev:two` (agents on loopback) you can also read a random
   PIN on B with `curl http://127.0.0.1:8766/api/pair`. With `--host <B_IP>` that does not work (P2-12).
2. On **A**, use the dashboard's **Pair Device** dialog (address `<B_IP>:8765`, PIN), or:
   ```powershell
   Invoke-RestMethod -Method Post -Uri http://<A_IP>:8765/api/pair -ContentType application/json -Body '{"addr":"<B_IP>:8765","pin":"246810"}'
   ```
   ```bash
   curl -X POST http://<A_IP>:8765/api/pair -H 'content-type: application/json' -d '{"addr":"<B_IP>:8765","pin":"246810"}'
   ```
3. Check: `GET /api/devices` on both laptops lists both, and A's `GET /api/stats` has B's live stats
   (updated every second). Three wrong PINs lock pairing for 15 s.

The pairing is remembered in `--home`. Next time, start both agents and they reconnect.

## 6. Wifi run

Both laptops on the same wifi (not a guest network with client isolation). Start both agents with
their **wifi** IP (step 4) and pair (step 5).

- Check the link type with `curl http://<A_IP>:8765/api/transport/link-quality`, which shows `"link": "wifi"`
  plus RTT, Mbps and loss. A migration's status (`GET /api/migrations`) also has `"link": "wifi"`.
- Known: B's side labels the incoming link "cable" (P2-11). Read the link type on **A**.

## 7. Cable run (direct ethernet or USB networking)

1. Connect the laptops: an ethernet cable (directly, or with USB-C ethernet adapters), a Thunderbolt
   bridge (two Macs), or USB tethering. With USB tethering, laptop B shares a link over USB and gets an
   address like `192.168.42.x` (Android) or `172.20.10.x` (iPhone hotspot).
2. Give the cable interface an IP on each side:
   - Wait about 30 s. Without DHCP both sides self-assign a link-local `169.254.x.x` address, which works.
   - Or set static IPs for a predictable demo: A `10.10.0.1/24`, B `10.10.0.2/24`, no gateway.
     - Windows: `New-NetIPAddress -InterfaceAlias "Ethernet" -IPAddress 10.10.0.1 -PrefixLength 24`
     - macOS: System Settings > Network > the adapter > Details > TCP/IP > Manually
     - Linux: `sudo ip addr add 10.10.0.1/24 dev eth0`
3. Check that the cable interface has an IP and that the other side answers:
   - `ipconfig` / `ifconfig` / `ip -4 addr` shows the address on the cable adapter (not on Wi-Fi).
   - `ping <other cable IP>` answers.
   - `Test-NetConnection <other cable IP> -Port 8765` / `nc -vz <other cable IP> 8765` succeeds once the agents run.
4. Start both agents with `--host <cable IP>` and pair using B's **cable** IP: `{"addr":"10.10.0.2:8765", ...}`.
   If they were already paired over wifi, re-pair over the cable so B's cable address is stored.
5. The agent shows CABLE when:
   - `GET /api/transport/link-quality` on A shows `"link": "cable"`.
   - The dashboard's Peer Transport card shows **CABLE**.
   - The migration status and metrics (`GET /api/migrations/{id}/metrics`) show `"link": "cable"`.
   The adapter name decides the label: names with `Ethernet`, `eth`, `enp`, `enx`, `usb`, `rndis`,
   `thunderbolt` or `bridge`, or a `169.254.` / `192.168.42.` / `172.20.10.` address, are cable.
   Names with `Wi-Fi` or `wlan` are wifi.
6. Optional failover demo: start both agents with `--host 0.0.0.0` on a laptop **without** virtual
   adapters, so both the cable and the wifi addresses are advertised (cable preferred). Unplug the
   cable during an idle period: the link falls back to wifi. To force one:
   `POST /api/transport/force-link {"link":"wifi"}` or `{"link":"cable"}`.

## 8. Demo order

Start counter_job on A once:

```bash
curl -X POST http://<A_IP>:8765/api/workloads/start -H 'content-type: application/json' -d '{"manifestPath":"tests/fixtures/counter_job"}'
```

`GET /api/workloads/runs` shows `count=N` growing. B's id comes from `GET /api/devices` on A.

1. **Devices and live stats:** both dashboards show both laptops, live CPU/RAM/battery and the link card.
2. **User command, MIGRATE:**
   `POST /api/migrations {"workloadId":"counter-job","targetId":"<B id>"}`. Watch the phases, the 6
   checkpoints plus the code unit, then COMPLETED. B's runs show `resumed count=N runs=2` and keep
   counting. A's copy is stopped. Show `interruptionMs` and `GET /api/migrations/{id}/metrics`.
3. **Migrate back (B to A):** the same call on B with A's id. Only the changed checkpoint is sent
   (the metrics show the others as skipped) and the epoch goes from 1 to 2.
4. **Low battery trigger, auto mode:** on A, `PUT /api/settings {"mode":"auto"}`, then
   `POST /api/dev/stats-override {"deviceId":"<A id>","stats":{"battery":{"pct":5,"charging":false}}}`
   (shown as SIMULATED). A recommendation with reasons appears, and the job migrates by itself.
   Clear it with `{"deviceId":"<A id>","stats":null}`. Change only **A's** stats: a peer's low
   battery wrongly moves A's workload (P3-6).
5. **REMOTE_ACCESS:** start a workload that B cannot run, then migrate it. `examples/gpu_only_job` needs
   a GPU and `torch-cuda`, so it works when B has no NVIDIA GPU. Or restart B with
   `--sim-profile arm64-lowspec` and use an x86-only manifest. The decision is REMOTE_ACCESS with
   a block reason, the job keeps running on A, and a remote session for B is pending A's consent.
6. **Rollback:** start with `TELEPORT_DEV_SLOW_TRANSFER_MS=400` on A, start a migration and close B's
   agent (Ctrl+C) during TRANSFERRING. The result is ROLLED_BACK with the reason, and A never stopped counting.
7. **History:** `GET /api/history/migrations` and `/api/history/decisions` show everything with reasons,
   also after restarting an agent.
8. **Cable:** repeat 2 over the cable and point at `"link": "cable"` and the higher throughput in the metrics.

## 9. If something goes wrong

| Symptom | Check |
| --- | --- |
| Pairing says "Failed to connect" | Firewall (step 2), the right IP, same network, `Test-NetConnection` / `nc` |
| Pairing says invalid PIN or rate limited | Use B's `TELEPORT_DEV_PIN`, wait 15 s after 3 wrong tries |
| Peers paired but no peer stats | Both agents bound to the IP the other one can reach (`--host`) |
| Link shows cable on wifi | Read it on A (P2-11). On a Mac, en0 is advertised as cable (P2-9): bind with `--host` |
| A migration waits in STARTING_TARGET | The link dropped after `mig.start`: reconnect, or `POST /api/migrations/{id}/abort` |
| Start over | Stop the agents, delete the `--home` folder, start again and re-pair |
