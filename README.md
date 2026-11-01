# Teleport (Claude's Angels, Bit N Build 2026 Finals)

Teleport keeps a running workload accessible across devices: it either migrates the workload with its
state (checkpoint by checkpoint, hash-validated, single active instance via epoch fencing) or keeps it
running and gives remote access. Every decision comes with reasons.

- Workflow, ownership and rules: [docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md)
- Two-laptop demo: [docs/RUNBOOK.md](docs/RUNBOOK.md); test status: [docs/TEST_MATRIX.md](docs/TEST_MATRIX.md); open issues by owner: [docs/INTEGRATION_ISSUES.md](docs/INTEGRATION_ISSUES.md)
- Contract (source of truth, changes via P1): [contract/contract.ts](contract/contract.ts), mirrored in
  [contract/contract.py](contract/contract.py)

## Quick start (demo laptops)

Double-click **`Teleport.cmd`** (Windows) or **`teleport.command`** (Mac). The first start installs
everything; then the dashboard opens. Pair, start and migrate from there: see [docs/RUNBOOK.md](docs/RUNBOOK.md).

## Install

Needs Python 3.11+ and Node 20+.

```bash
python -m venv .venv
```

Activate it (`.venv\Scripts\activate` on Windows, `source .venv/bin/activate` on macOS/Linux; the npm
scripts find `.venv` even when it is not activated), then:

```bash
pip install -e agent
```

```bash
npm install
```

`pip install -e agent` installs every Python dependency the team needs (runtime, pytest, ruff, mypy).
`npm install` installs every UI dependency. Only P1 edits `agent/pyproject.toml` and `package.json`.
For `npm run e2e`, also run `npx playwright install chromium` once.

## Commands

| Command | What it does |
| --- | --- |
| `npm run dev:two` | Agent A on :8765 (`.teleport-dev/a`, profile `default`), agent B on :8766 (`.teleport-dev/b`, profile `arm64-lowspec`), UI dev server on :5173 |
| `npm run dev:agent` | One agent with env settings (`TELEPORT_PORT`, `TELEPORT_HOME`, `TELEPORT_SIM_PROFILE`, `TELEPORT_NAME`, `TELEPORT_HOST`) |
| `npm run dev:ui` | UI dev server only (proxies `/api` and `/ws` to `TELEPORT_AGENT`, default A) |
| `npm run build` | Typecheck and build the UI into `ui/dist` (the agent serves it at `/`) |
| `npm test` | pytest (`tests/`) |
| `node scripts/py.mjs -m pytest tests/migration/e2e` | Integration scenarios 1 to 4 with real agents (pair, migrate, remote access, target crash) |
| `npm run test:ui` | Vitest (`ui/src/**/*.test.tsx`, `tests/ui/**/*.test.tsx`) |
| `npm run e2e` | Playwright (`tests/ui/e2e`) |
| `npm run typecheck` | mypy strict + `tsc` strict |
| `npm run lint` / `npm run format` | ruff + eslint / ruff format |

The UI on :5173 talks to agent A. Open `http://localhost:5173/?agent=http://127.0.0.1:8766` to view B.
Agent CLI flags override env: `python -m teleport --port 8766 --home .teleport-dev/b --sim-profile arm64-lowspec`.
Simulated profiles live in `agent/teleport/core/sim_profiles/` and everything they produce is marked `simulated`.
`TELEPORT_DEV_SLOW_TRANSFER_MS=400` slows each migration chunk down for demos.
By default an agent binds 127.0.0.1; set `TELEPORT_HOST=0.0.0.0` for a real two-device setup.

## Workloads and the SDK

A workload is a folder with a `teleport.yaml` (sample: [tests/fixtures/teleport.yaml](tests/fixtures/teleport.yaml))
and code that uses `teleport_sdk` (in `sdk/`, standard library only):

```python
import teleport_sdk as teleport

teleport.init()
state = teleport.restore("counter") or {"count": 0}  # None if never saved
teleport.on_fence(lambda: teleport.checkpoint("counter", state))  # final checkpoint before cutover
while not teleport.should_stop():
    ...
    teleport.checkpoint("counter", state, files=["out/log.txt"])
```

Start it with `POST /api/workloads/start {"manifestPath": "tests/fixtures/counter_job"}`. The agent copies
the folder to `TELEPORT_HOME/workloads/<id>/work`, restores any saved checkpoints, and runs `command` there
(`python` means the agent's interpreter, with `sdk/` on `PYTHONPATH`). Logs go to `.../logs/run.log`, and
checkpoints go to `.../checkpoints/<id>/`. Run without an agent, the SDK saves to `./.teleport-local`.

## Architecture

```
        Device A (agent :8765)                                   Device B (agent :8766)
 +-------------------------------------+   encrypted peer link   +-----------------------+
 |  FastAPI  /api/*  /ws/events  ui/   |<=======================>|  same agent           |
 |  ---------------------------------  |   (wifi or cable)       |                       |
 |  core: Context, EventBus, Settings  |                         |                       |
 |   devices   transport   security    |                         |                       |
 |   feasibility orchestration history |                         |                       |
 |   migration authority   remote      |                         |                       |
 +-------------------------------------+                         +-----------------------+
            ^  REST + WebSocket
            |
   Dashboard (ui/, React) on :5173 in dev, served from ui/dist by the agent otherwise
```

Modules only meet through `ctx.bus` (typed `BusEvent`s) and the Protocols in `contract/contract.py`.
`create_app()` (agent/teleport/core/app.py) builds the Context, calls each `create_*(ctx)` entry
function, starts services (`startup()`/`shutdown()`), and mounts the REST routes from the contract
(agent/teleport/core/api.py). The current modules are stubs from P1: each owner replaces its own
`__init__.py` while keeping the entry function and the Protocol. A stub action that is not built yet
returns HTTP 501.

## Rules

- Push all your work here. Don't rewrite history (no force-push, no deleting branches). It gets checked.
- Don't commit secrets or .env files. Commit a .env.example instead.
- Don't change the repo visibility and don't add anyone outside your team.
- Anything unclear, ask the council.
