# SOUL EXTER

**An autonomous trading floor where every idea is a person.**

A fly-brain market hunter sniffs the tape, and every trade it finds walks into a real 3D
trading hall through the *welcome door*, sits at a desk, stands up, and then goes cabin to
cabin — five LLM desks, one at a time, physically inside each cabin — before a sixth desk
(**SOVEREIGN**, the Head of Council / CEO) rules on any split. Agreed tickets walk to the
entry gate. Rejected tickets walk out of the exit door.

The whole product runs on a **free Kaggle GPU** — nothing heavy on your laptop.

```
                         ┌──────────────── the floor ────────────────┐
  market tape ──► FLY BRAIN ──► welcome gate ──► desk (sit) ──► cabin 1..5 ──►
                         │                                          │
                         │                     3–4 approve & dissent │
                         │                                          ▼
                         └──────────────────────────────────► CEO (cabin 6)
                                                                    │
                                        approve ──► entry gate ─────┘
                                        reject  ──► exit door
```

---

## What you see

| Zone | What happens there |
| --- | --- |
| **Welcome gates** (south wall) | Tickets enter from the street; rejected tickets leave through the exit gate |
| **Trading pit** (36 desks, 6 pods) | Every discovered trade gets its own desk, a seated trader and a live screen |
| **Cabins 01–05** | LLM judges hear the ticket *inside* the cabin, at the hearing table, then vote |
| **Executive cabin** | The 6th LLM (CEO) receives the whole record — every stage's reasoning, confidence and evidence — when the council splits |
| **Data vault** | Playbook buckets, realised track record, tail events |
| **Debate chamber** | All six desks debate, challenge, concede and ratify training notes continuously |
| **Corridor / concourse** | Clean pathways only — walkers are routed on a navmesh built from the same blueprint that renders the room |

Floating labels ride above every head — seated, walking, inside a cabin — with the trade or
agent it belongs to. Above each cabin: the judge's name, model and its verdict on the ticket
currently in front of it, plus a chat box to interrogate that judge about that specific ticket.

## The six desks

| Cabin | Name | Mandate | Default open-source model |
| --- | --- | --- | --- |
| 01 | **ATLAS** | Trend structure & market regime | Llama 3.1 70B |
| 02 | **QUANTA** | Expectancy, cost, sample size | Qwen2.5 72B |
| 03 | **MERIDIAN** | Macro & session liquidity | DeepSeek-V3 |
| 04 | **VOLTA** | Volatility & options expression | Mixtral 8x22B |
| 05 | **VECTOR** | Execution & microstructure | phi-4 |
| — | **SOVEREIGN** | Head of Council · final mandate | Hermes-3 405B |
| hunt | **DROSOPHILA** | Fly-brain market hunter | Qwen2.5 32B (narrates its strikes) |

Every seat runs a **built-in analyst engine** by default (no keys, no network, microseconds
per verdict). Paste an API key in *Settings → LLM Council* and that seat is promoted to a
hosted open-source model through any OpenAI-compatible endpoint (OpenRouter, Together, Groq,
DeepSeek, Mistral, Ollama, custom). Keys are stored on the host machine only.

## Settings panel

- **Markets** — tick boxes for the whole universe: 27 FX pairs, 30 stocks, 12 indices,
  12 futures, 12 options, 24 crypto. `ALL` / `NONE` per class. Only ticked instruments are
  hunted.
- **LLM Council** — every seat's name, specialty, model, provider, base URL, temperature,
  enable switch, API-key field and a **TEST SEAT** button.
- **Engine** — strike threshold, scan interval, symbols per burst, cooldown, how many tickets
  may be on the floor at once, ambient traders, live-venue merge, paper evaluation.

## The trade lifecycle (exactly as it runs)

1. **Hunt** — the fly scans the enabled universe. A strike is only emitted when the tape is
   *directional* (efficiency above the calibrated floor) **and** the trend composite is real.
   Direction follows the trend; the ticket gets a 1.0×ATR stop and a 2.2×ATR target.
2. **Welcome** — the ticket walks in from outside, through the welcome gate, to its desk.
3. **Desk** — it sits down. The fly dives over to inspect the desk it just filled.
4. **Cabins 1–5** — it stands up and walks to cabin 01, enters through the cabin door, stands
   at the hearing table for the hearing, then leaves and walks to cabin 02, and so on.
   Each judge sees only the ticket, the tape evidence, the playbook base rates and the
   reasoning of the cabins before it — no peeking ahead.
5. **Ruling** — five verdicts. Five or four approvals escalate the ticket to the CEO with the
   full record; two approvals or fewer is an outright veto; a split goes to the Head of
   Council with every stage's reasoning attached.
6. **Settlement** — approved tickets walk to the entry gate and are paper-evaluated
   (realised R). Rejected tickets walk out of the exit door, and the counterfactual is still
   tracked (`cf_r`) so the floor can see what the veto saved or cost.

## Does it make money?

Yes, on the tape it is calibrated against — and the number is measured, not asserted:

```
python3 tests/track_record.py 300 16     # 300s wall clock, 16x floor speed
ACCEPTED (real book) : n=28 wins=46% sum=+13.60R mean=+0.486R
```

The council's own discrimination is measured too, out of sample:

```
python3 scripts/council_study.py --symbols 20 --cycles 26 --seed 4242
COUNCIL accept n=77 (69%) mean +0.704R | reject n=34 mean -0.169R
```

That is the honest way to read the product: **the entry gate carries the edge; the council
filters and sizes it.** On a frozen random tape there is no free lunch, so the edge is
*calibrated into the tape and then learned back out of it*:

| Script | Question it answers |
| --- | --- |
| `scripts/edge_study.py` | Where does the tape actually pay? (feature-conditioned hit rates) |
| `scripts/geometry_study.py` | Which stop/target/horizon pays? |
| `scripts/rule_study.py`, `scripts/grid_study.py` | Which entry rule survives other seeds? |
| `scripts/character_study.py` | Which market character makes the mandate earnable? |
| `scripts/train_scorecards.py` | Which evidence predicts realised R? (fits the desks' model) |
| `scripts/council_study.py` | Do the six desks separate winners from losers? |
| `tests/track_record.py` | What does the whole floor actually earn? |

Calibrated defaults (multi-seed): efficiency ≥ 0.32, |trend composite| ≥ 0.30, stop 1.0×ATR,
target 2.2×ATR, 600s evaluation window → **+0.49R mean, worst seed +0.19R**.

Every closed trade also feeds the playbook (buckets, hit rates, tail events) and the fly's
Hebbian read-out, so the floor keeps re-training itself from its own results — and the debate
chamber ratifies a running list of lessons.

## Live markets

`market/live.py` merges real venue prices when the host has network: Binance klines for
crypto, Yahoo chart data for everything else — no API keys. When a venue is unreachable the
floor keeps trading a regime-switching synthetic tape anchored to the last real print, so the
product never stops. The footer of the UI always says which tape you are watching.

## Run it

### On a free Kaggle GPU (recommended)

Open `kaggle/soul_exter_kaggle.ipynb` (GPU T4, Internet on) and run the cells: it installs the
two API dependencies, builds the React/three.js interface, optionally runs the track-record
test, starts the floor, and prints a public URL. Nothing is installed on your laptop and no
GPU is used locally.

### Locally, for development

```bash
# backend
cd backend
pip install fastapi "uvicorn[standard]" httpx numpy
python3 -m uvicorn soul_exter.api.server:app --host 0.0.0.0 --port 8000

# interface (proxies /api and /ws to the backend)
cd frontend
npm install
npm run dev            # http://localhost:5173
```

Headless checks:

```bash
cd backend
python3 tests/smoke_engine.py 50 10       # boot, walk order, navmesh safety
python3 tests/track_record.py 300 16      # realised book
```

## Architecture

```
backend/soul_exter/
  core/layout.py     blueprint of the floor: rooms, walls, doors, desks, props, signs,
                     waypoints + the A* NavGrid (one source of truth for render & routing)
  core/engine.py     20 Hz floor: trades walk spawn→desk→cabins→CEO→entry/exit, NPCs,
                     events, snapshots, paper outcomes, live-venue merge
  core/settings.py   persisted runtime settings (markets, thresholds, seats)
  market/feed.py     regime tape + venue merge, session-aware volatility
  market/universe.py 117 instruments across six asset classes
  market/live.py     key-less Binance/Yahoo bridge
  brain/flybrain.py  spiking fly brain: 12→26 PN→140 KC (k-WTA)→8 MBON, Hebbian read-out
  brain/features.py  12 glomeruli, trend composite, signal levels
  brain/scanner.py   the hunt: rotating scan, gates, funnel telemetry
  llm/registry.py    the seven seats
  llm/analyst.py     built-in specialist scorecards (per-desk narrative)
  llm/expectancy.py  calibrated expectancy model the desks vote on
  llm/engine.py      hearings, CEO arbitration, debate turns, chat
  llm/playbook.py    bucket memory: hit rates, tail events, expectations
  api/server.py      REST + /ws (12 Hz frames) + SPA hosting
frontend/src/
  three/world.ts     materials, canvas textures, floor/walls/doors/desks/props/city
  three/person.ts    articulated people, gait, nameplates, holo trade cards
  three/scene.ts     FloorScene: 12 Hz lerped walkers, camera presets, labels, ticker,
                     cabin hearing rings, verdict flashes, auto quality degrade
  ui/App.tsx         HUD, dock, panels, settings
  ui/panels.tsx      pipeline, trade journey, council, debate room, fly brain, markets,
                     analytics, settings
```

The scene is served from the same origin as the API, so a single port exposes everything, and
the browser never talks to `localhost` for data.

## Performance

Positions arrive at ~12 Hz and are interpolated every display frame, so walking stays smooth
regardless of the sim rate. Geometry is instanced/shared-material, labels are DOM elements
projected from world space, and the renderer degrades itself (pixel ratio, shadows) if the
frame rate drops below ~38 fps for a few seconds. A `CINEMA` button hides the panels for a
full-screen view of the floor.

## Honest notes

- The default tape is synthetic (regime-switching with persistent order flow and dealer fade)
  because the floor must work with no keys and no internet. It is *calibrated* — the scripts
  above measure the structure, and the desks' model is fitted to realised outcomes — but it is
  not a prediction about any real market.
- Live-venue merging is wired and syntax-checked, but on a host without egress it falls back to
  the synthetic tape (the UI states which one is live).
- Paper evaluation only: no venue orders are ever placed.
