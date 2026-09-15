# SOUL EXTER — Laptop Setup Guide

Run the whole trading floor on your own machine: 3D hall + fly brain + 6 LLM desks.
Nothing here needs a GPU, a paid API key, or Docker.

---

## 1. What you need installed

| Tool | Version | Check with | Get it from |
| --- | --- | --- | --- |
| **Git** | any recent | `git --version` | https://git-scm.com/downloads |
| **Python** | 3.10 – 3.12 (3.11 tested) | `python --version` | https://www.python.org/downloads/ (Windows: tick **"Add python.exe to PATH"** in the installer) |
| **Node.js** | 18 or newer (22 tested) | `node --version` | https://nodejs.org (choose **LTS**) |
| **Browser** | Chrome / Edge / Firefox with WebGL | — | you already have one |

Hardware: any laptop from the last ~8 years. ~1 GB free disk for dependencies.
Internet is needed once for installs — and afterwards for live prices + the free
cloud GPT (both optional; the floor falls back to a synthetic tape and a built-in
reasoning engine when offline).

---

## 2. Get the code

```bash
git clone https://github.com/Naserkhan07/soul_exter.git
cd soul_exter
```

> The **enlarged 48-desk trading floor** (commit `3903919`) is on the branch
> `arena/01a0a384-soul-exter` until it is merged into `main`. To get it now:
>
> ```bash
> git clone -b arena/01a0a384-soul-exter https://github.com/Naserkhan07/soul_exter.git
> cd soul_exter
> ```

---

## 3. Easiest start — one command

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_local.ps1
```

**macOS / Linux:**
```bash
./scripts/run_local.sh
```

The script installs backend + frontend dependencies, builds the interface, and
serves **UI + API + live feed on one origin**. When it says *floor ready*, open:

```
http://localhost:8000        ← the trading floor
http://localhost:8000/docs   ← REST API explorer
```

Useful switches:
```bash
PORT=9000 ./scripts/run_local.sh     # different port
DEV=1     ./scripts/run_local.sh     # hot-reload UI on :5173 + API on :8000
```

Stop it with **Ctrl+C** in the terminal.

---

## 4. Step-by-step setup (recommended for development)

### 4.1 Backend (Python / FastAPI)

From the repo root:

```bash
# one-time: create an isolated Python environment
python -m venv .venv

# activate it — Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Windows cmd:
.\.venv\Scripts\activate.bat
# macOS / Linux:
source .venv/bin/activate

# install the 4 backend packages (fastapi, uvicorn, httpx, numpy)
pip install -r backend/requirements.txt
```

Start the floor engine:

```bash
cd backend
python -m uvicorn soul_exter.api.server:app --host 0.0.0.0 --port 8000
```

Leave this terminal running. Sanity-check in a **second** terminal:

```bash
curl http://127.0.0.1:8000/api/layout
# → JSON containing "desks": [ ... 48 desks ... ] means the enlarged floor is live
```

(`curl` on Windows: use `start http://127.0.0.1:8000/docs` in a browser instead.)

### 4.2 Frontend (React + three.js, hot reload)

Open a **second terminal** in the repo root:

```bash
cd frontend
npm install        # one-time, ~1–2 min
npm run dev
```

Open **http://localhost:5173** — this dev server proxies `/api` and `/ws` to the
backend on port 8000 automatically (see `frontend/vite.config.ts`). Editing any
frontend file hot-reloads in the browser.

### 4.3 Alternative: single port, production build

Instead of 4.2 you can build the interface into the API server:

```bash
cd frontend
npm install
npm run build      # outputs frontend/dist — the backend serves it automatically
```

Then only **http://localhost:8000** matters (backend must be running).

---

## 5. First-minute checklist in the browser

1. The 3D hall loads — big pit with **48 desks**, 5 glass review cabins, executive
   chamber, debate chamber, ticker bands over the floor.
2. Top-right **☀ DAY / ☾ NIGHT** — the whole city switches; default is NIGHT.
3. Camera presets along the UI (overview / pit / corridor / cabins / executive /
   debate / gates / tape).
4. Click any seated desk and ask it **anything** — "explain ETFs", "capital of
   Japan?" — every desk answers ChatGPT-style via the **free keyless cloud GPT**,
   strictly about your question. No key needed.
5. Watch the fly brain hunt: a trade spawns at the welcome gate, sits at a desk,
   then walks cabin-to-cabin for the 5 judges → CEO ruling → entry/exit gate.

Headless engine check (no browser):

```bash
cd backend
python tests/smoke_engine.py 30 8     # 30s sim x8 speed: walk order + navmesh safety
```

---

## 6. Optional configuration

### 6.1 Hosted LLM keys (optional — desks already work keyless)

With **zero keys** every desk uses the free keyless GPT endpoint, with a built-in
offline engine as final fallback. To upgrade specific desks to hosted models, put
keys in a `.env` file at the repo root (picked up by the `run_local` scripts):

```
OPENROUTER_API_KEY=sk-or-...     # ATLAS (cabin 1) + NAVEED (CEO)
TOGETHER_API_KEY=...             # QUANTA (cabin 2) + DROSOPHILA (fly scout)
DEEPSEEK_API_KEY=...             # MERIDIAN (cabin 3)
MISTRAL_API_KEY=...              # VOLTA (cabin 4)
GROQ_API_KEY=...                 # VECTOR (cabin 5)
```

For manual runs, export these in the shell before starting uvicorn
(`export OPENROUTER_API_KEY=...` / PowerShell: `$env:OPENROUTER_API_KEY="..."`).
You can also paste keys per-desk in the running app: **Settings → LLM Council**.

All desk behaviour (names, models, providers, keys, temperatures) persists to
`soul_exter_settings.json` at the repo root — created on first run.

### 6.2 Real execution via MetaTrader 5 (optional, Windows only)

The floor is paper-trading by default. To route accepted tickets to a real MT5
terminal on this machine:

```bash
pip install MetaTrader5

# prove the pipe without placing anything:
python tools/mt5_check.py --login <LOGIN> --server <SERVER>          # connection test
python tools/mt5_bridge.py --floor http://localhost:8000 --dry-run   # bridge dry-run
```

Then in the app: **Settings → execution**: `broker_mode = mt5`, your login /
password / server, and `auto_place` when you are ready. Keys stay on your laptop
and are never committed.

### 6.3 Markets

Live prices merge automatically when the machine has internet (Binance for
crypto, Yahoo for everything else — no keys). Offline, a regime-switching
synthetic tape keeps the floor alive. The UI footer always names the tape.

---

## 7. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `pip install` refused (externally-managed environment, Ubuntu 23+/Fedora) | use the venv from step 4.1, or append `--break-system-packages` |
| `python` not found on Windows | reinstall Python and tick *Add to PATH*, or use `py -3.11 -m venv .venv` |
| Port 8000 already in use | `PORT=9000 ./scripts/run_local.sh`, or `--port 9000` on uvicorn; dev UI then proxies fine after `SOUL_EXTER_BACKEND=http://127.0.0.1:9000 npm run dev` |
| Port 5173 busy in dev mode | Vite auto-moves to 5174 — read the URL it prints |
| PowerShell blocks `run_local.ps1` | `powershell -ExecutionPolicy Bypass -File scripts\run_local.ps1` |
| Desk answers are labelled *offline fallback* | no internet or the free GPT endpoint is blocked from your network; desks still answer using the built-in engine, or add a hosted key (6.1) |
| Black screen / no 3D | enable hardware acceleration in browser settings; Chrome/Edge: `chrome://gpu` should list WebGL |
| Windows firewall prompt on first start | allow on **private networks** (the server binds 0.0.0.0 for phone-on-same-WiFi viewing too) |
| `npm install` very slow | normal on first run; repeated installs are cached |

---

## 8. Daily use

```bash
# terminal 1
cd backend && .\.venv\Scripts\activate      # (mac/linux: source .venv/bin/activate)
python -m uvicorn soul_exter.api.server:app --host 0.0.0.0 --port 8000

# terminal 2 (only if you want hot-reload dev mode)
cd frontend && npm run dev
```

→ open **http://localhost:8000** (built UI) or **http://localhost:5173** (dev UI).
Ctrl+C stops each server. Everything runs locally; the only outbound calls are
market prices and the free GPT endpoint, both optional.

No GPU is used on the laptop — the heavy lifting is a few million float ops per
tick in numpy.
