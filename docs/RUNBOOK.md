# Teleport demo runbook: two laptops, no terminal

Laptop **A** has the project and starts it. Laptop **B** receives it. Everything happens in the
dashboard. The only "command" is double-clicking the Teleport launcher on each laptop.

## Once per laptop (before the demo)

1. Install **Python 3.11+** (Windows: tick "Add python.exe to PATH") and **Node.js 20+**.
2. Install **VS Code** on both laptops (needed for the VS Code demo).
3. Get the repo (the same `main` on both laptops), for example with GitHub Desktop or the green
   **Code > Download ZIP** button, then unzip.
4. Double-click the launcher in the repo folder:
   - Windows: **`Teleport.cmd`**
   - Mac: **`teleport.command`**. If macOS says it cannot run it: right-click > Open, or once in
     Terminal: `chmod +x teleport.command`.

   The first start installs everything (a few minutes) and builds the dashboard. Later starts take seconds.
5. **Firewall:** Teleport uses TCP 8765 and UDP 8767.
   - **Windows:** the launcher asks once "Allow Teleport through the firewall?" (an admin prompt):
     click **Yes**. If Windows instead shows "Windows Defender Firewall has blocked some features of
     python.exe", tick **both Private and Public** and click Allow.
   - **Mac:** "Do you want python3 to accept incoming connections?" > **Allow**.

## The demo

Both laptops must be on the **same wifi** (no guest network: those block laptop-to-laptop traffic).
A phone hotspot works. For a cable: connect an ethernet cable (or USB-C adapters) and give both
cable adapters an address, or let them self-assign `169.254.x.x` (wait about 30 s).

1. **Start Teleport on both laptops:** double-click the launcher. A black window stays open (that
   is the agent; close it to stop Teleport) and the dashboard opens in the browser.
   Each dashboard shows **Pairing PIN 123456** in the top bar.
2. **Pair (on A):** click **Pair Device**. Laptop B appears under **Nearby devices** after a
   couple of seconds. Click **Select**, type the **PIN shown on B's screen**, click
   **Pair & Connect**. Both dashboards now show both laptops and their live stats.
3. **Open the project (on A):** **Workloads** page > **VS Code project**. Paste the folder of the
   project (in Explorer: right-click the folder > *Copy as path*), then click **Open in VS Code**.
   VS Code opens with the project. Work in it: open a few files, move the cursor, type something
   and **do not save**.
4. **Migrate (on A):** on the project's card click **Migrate**, then pick Laptop B under
   **Evaluate & Migrate**. The **Migration** tab opens and shows the steps live:
   evaluating, transferring, validating, fencing, starting target, completed. It also shows the
   authority moving to B (epoch 1) and the interruption time (about 0.2 s).
5. **On B:** VS Code opens with the same project, the same tabs, the same cursor positions and the
   **unsaved edits still unsaved**. A's VS Code window has closed (never two copies).
   The status bar on B says "Teleport: editor restored".
6. **Migrate back (on B):** B's **Workloads** page shows the project. Click **Migrate** and pick A.
   Only what changed travels back.

Other demos from the same pages:

- **Counter demo** (Workloads > Counter demo > Start): a job that counts. After migrating, it
  continues from the same number on the other laptop.
- **Automatic migration:** Settings > mode **auto**, then use the stats simulator to drop A's
  battery to 5 % (shown as SIMULATED). Teleport recommends and migrates by itself.
- **Remote access:** if B cannot run a workload (for example no VS Code installed there),
  Teleport chooses **Remote access** instead, with the reasons, and the workload stays on A.
- **History:** every migration and decision with its reasons, also after restarting.

## If something does not work

| What you see | What to do |
| --- | --- |
| B does not appear under Nearby devices | Same wifi? Not a guest network? Firewall allowed on both (step 5). You can also type B's address (`ip:8765`, see B's Teleport window). |
| "Invalid PIN" | Use the PIN in the top bar of **B's** dashboard. After 3 wrong tries, wait 15 s. |
| The decision is Remote access instead of migrate | The Migration tab lists why: for example "Target has 248 MB free RAM". Close some apps on B, or install VS Code there. |
| VS Code does not open | Install VS Code, or point Teleport to it: set `TELEPORT_VSCODE` to the path of `Code.exe` (Windows) or the `Visual Studio Code.app/Contents/MacOS/Electron` binary (Mac). |
| A migration waits in "Starting target" | The link dropped right at the switch-over. Teleport waits until it knows which laptop has the project (never two copies). Reconnect, or click Abort. |
| Start over | Close both Teleport windows, delete the `.teleport` folder in your user folder, start again and pair again. |

## How it works (for questions from the judges)

- The project folder and the editor state (`project/.teleport-vscode/state.json`: open tabs,
  active tab, cursors, scroll, unsaved buffers) are a Teleport checkpoint. A small VS Code
  extension keeps that file current and restores it on the other laptop.
- Transfer: chunks hashed with SHA-256, encrypted with AES-256-GCM (Ed25519 + X25519 pairing),
  verified on B. Authority moves only after everything is validated and B has started, with an
  epoch so the old copy can never come back.
- Limits: what moves is the project files and the editor state, not the process memory.
  Terminals, debug sessions and extensions' internal state start fresh on B.
