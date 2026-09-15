# SOUL EXTER

**An autonomous trading floor where every idea is a person.**

A fly-brain market hunter sniffs the tape, and every trade it finds walks into a real 3D
trading hall through the *welcome door*, sits at a desk, stands up, and then goes cabin to
cabin — five LLM desks, one at a time, physically inside each cabin — before a sixth desk
(**NAVEED**, the Head of Council / CEO) rules on any split. Agreed tickets walk to the
entry gate. Rejected tickets walk out of the exit door.

The whole product runs on a **free Kaggle GPU** — nothing heavy on your laptop.

```
                         ┌──────────────── the floor ────────────────┐
  market tape ──► FLY BRAIN ──► welcome gate ──► desk (sit) ──► cabin 1..5 ──►
                         │                                          │
                         │              ┌──── 5/5 unanimous ──► entry gate
                         │              │
                         │     3–4 approve & dissent
                         │              ▼
                         └──────────────────────────► CEO (cabin 6)
                                                        │
                            approve ──► entry gate ─────┘
                            reject  ──► exit door       (≤2 approve ──► exit door,
                                                         straight from the cabins)
```

---

## What you see

| Zone | What happens there |
| --- | --- |
| **Welcome gates** (south wall) | Tickets enter from the street; rejected tickets leave through the exit gate |
| **Trading pit** (36 desks, 6 pods) | Every discovered trade gets its own desk, a seated trader and a live screen |
| **Cabins 01–05** | LLM judges hear the ticket *inside* the cabin, at the hearing table, then vote |
| **Executive cabin** | The 6th LLM (CEO) receives the whole record — every stage's reasoning, confidence and evidence — whenever the council splits 3–1 / 4–1. A unanimous 5/5 board skips the chamber and walks straight to the entry gate |
| **Data vault** | Playbook buckets, realised track record, tail events |
| **Debate chamber** | All six desks debate, challenge, concede and ratify training notes continuously |
| **Corridor / concourse** | Clean pathways only — walkers are routed on a navmesh built from the same blueprint that renders the room |
| **Orders desk** | Three live sections: **READY TO PLACE** (every cleared ticket waiting to be routed, each with a PLACE TRADE button), **PLACED · OPEN** (venue ticket, fill, lots, unrealised R and a BOOK TRADE button that closes instantly) and **BOOKED · CLOSED** (realised R / USD). A venue-positions table shows what the broker holds right now |
| **Execution (Broker tab)** | Paper by default; point it at MetaTrader 5 with your account, server and password and every PLACE TRADE goes out as a real venue order, forex pairs included. TEST / CONNECT verifies the terminal and shows the account it logged into |

Floating labels ride above every head — seated, walking, inside a cabin — with the trade or
agent it belongs to. Above each cabin: the judge's name, model and its verdict on the ticket
currently in front of it, plus a chat box to interrogate that judge about that specific ticket.

## Placing and booking trades

Open **ORDERS** in the right rail. Everything on this desk is one click:

1. **READY TO PLACE** — tickets the council has cleared that have no venue order yet. Each card
   carries the instruments' numbers (entry / stop / target / fly conviction / votes) and a
   **⇪ PLACE TRADE** button. Clicking it routes the order *immediately*: with Broker set to
   MT5 the fill comes back from your terminal, otherwise it is a paper fill. **⇪ PLACE ALL**
   routes every waiting ticket in one go.
2. **PLACED · OPEN** — every working position with its venue ticket, mode (PAPER / MT5), lots,
   fill price, live price, unrealised R and USD. **✕ BOOK TRADE** closes it instantly at the
   current price and banks the realised R.
3. **BOOKED · CLOSED** — the realised record, per ticket, with fill → book prices and P&L.
4. **VENUE POSITIONS** — read straight from the broker (the MT5 terminal's own position list
   when connected), so you can *see* that the order is live.
5. **VETOED BY THE CABINS** — refused tickets with their counterfactual R, so the veto quality
   stays visible.

Every ticket card in the trade dock carries the same two buttons, plus the venue ticket once it
is routed. A **"n ready to place"** chip in the status bar updates live.

### Why a PLACE TRADE can be "placed" without appearing in your MT5

Because the floor can only send an order **from the machine where the MetaTrader 5 terminal
runs** — the `MetaTrader5` python package drives a local terminal (Windows, or Linux/Wine); it
cannot dial a terminal over the internet. If the floor is hosted somewhere else (Kaggle, a
sandbox, a VPS) with Broker set to `mt5`, the desk falls back to the paper book and says so in
amber. Your account, login, server and password are stored and used *only* where that terminal
is reachable. Press **DIAGNOSE** in the ORDERS desk for a step-by-step verdict:

```
FAIL | MetaTrader5 package — ModuleNotFoundError: No module named 'MetaTrader5'
FAIL | everything else    — cannot continue without the package
```

Three ways to get real fills, pick one:

| Setup | What to do | Where the floor runs |
| --- | --- | --- |
| **A · local** | Broker = `mt5`, paste login / password / server, SAVE & CONNECT → badge turns MT5, DIAGNOSE goes green | same PC as the terminal |
| **B · bridge** | Broker = `mt5-bridge`, then run `tools/mt5_bridge.py` on the terminal PC → orders are executed there and the real tickets appear in the ORDERS desk | anywhere (Kaggle included) |
| **C · paper** | nothing to do — the paper book simulates fills | anywhere |

### The bridge (Kaggle floor + your home terminal)

```bash
# on your PC, next to the MetaTrader 5 terminal (logged into your account)
pip install MetaTrader5
python3 tools/mt5_bridge.py --floor https://<your-floor-url> \
    --login 112594843 --password 'your-password' --server MetaQuotes-Demo
```

It polls the floor's `/api/exec/queue`, sends the order with `order_send` (suffix-aware symbol
mapping, IOC filling, deviation cap, magic 770001, `SOUL-EXTER <ticket>` comment), and posts the
real ticket, fill price and position list back to `/api/exec/report`. The ORDERS desk then shows
`QUEUED FOR THE MT5 BRIDGE → MT5 <ticket>` plus the terminal's own live positions, and BOOK TRADE
sends a closing deal for that position ticket. No bridge running? The desk says
**BRIDGE OFFLINE** and nothing is faked.

Prove the pipe without a terminal first: `python3 tools/mt5_bridge.py --floor <url> --dry-run`
simulates the venue and reports back — that is exactly how this path is tested in CI.

### Check your own machine

```bash
python3 tools/mt5_check.py --login 112594843 --password '…' --server MetaQuotes-Demo
python3 tools/mt5_check.py --login … --server … --place EURUSD    # one 0.01 lot round trip
```

It prints the same checklist as DIAGNOSE (package → terminal → login → algo trading allowed →
symbol mapping incl. suffixes → live ticks) and, with `--place`, fires and closes a test order.

### Routing to MetaTrader 5 (why forex needs a local terminal)

The MT5 python package only works where the **terminal runs** — Windows, or Linux under Wine.
So there are two sensible setups:

* **Execution on your own machine** — run the backend locally (`python3 -m uvicorn
  soul_exter.api.server:app --host 0.0.0.0 --port 8000`), open *Settings → Broker*, choose
  **mt5**, paste login / password / server, set the symbol suffix your broker uses (e.g. `.m`
  for `EURUSD.m`), press **SAVE & CONNECT**. The Orders desk badge turns from PAPER to MT5 and
  the account line shows the login, balance and DEMO/LIVE flag it authenticated against.
* **Floor on Kaggle, execution at home** — run the whole floor on the Kaggle GPU session as
  usual and keep the paper book there; MT5 placement needs the backend on the machine with the
  terminal.

If MT5 is configured but unreachable the Orders desk says so in amber, explains the reason
(package missing / login refused / symbol not found) and keeps routing to the paper book —
it never silently pretends an order went to a venue.

## Every desk answers everything

Open **ASK ANY DESK** in the right-hand rail and you are talking to all seven desks (five
cabins, **NAVEED**, and the hunter). No ticket and no API key are required: each desk answers
from the built-in analyst engine when no hosted model is configured, and the answer always
carries the desk's own reasoning.

* **Ticket questions** — “why did you refuse the last ticket?”, “what would make you flip?”,
  “how would you size it?” Every desk answers with its recorded ruling *or*, if the walker has
  not reached its cabin yet, with its own model's live read of that ticket against the same
  tape: verdict, confidence, the evidence, the invalidation level and the clip.
* **Market questions** — “your read on gold?”, “should I short oil?” Live price, trend
  composite, efficiency, RSI and ATR percentile straight off the tape the scanner hunts on.
* **Process questions** — expectancy, R multiples, sizing, stops, greeks, basis and carry,
  execution, drawdown, psychology, backtesting, MT5.
* **Anything else** — arithmetic, the floor's own numbers, small talk; and if a question is
  genuinely outside the tape the desk says so honestly and tells you how to give it a hosted
  model that can answer it, rather than bluffing.

Every desk also shows a standing answer: its latest ruling (or live read) — symbol, verdict,
confidence and the written reason — in the COUNCIL tab, in the ASK ANY DESK header, and on the
plates floating above each cabin in the 3D hall.

## The six desks

| Cabin | Name | Mandate | Default open-source model |
| --- | --- | --- | --- |
| 01 | **ATLAS** | Trend structure & market regime | Llama 3.1 70B |
| 02 | **QUANTA** | Expectancy, cost, sample size | Qwen2.5 72B |
| 03 | **MERIDIAN** | Macro & session liquidity | DeepSeek-V3 |
| 04 | **VOLTA** | Volatility & options expression | Mixtral 8x22B |
| 05 | **VECTOR** | Execution & microstructure | phi-4 |
| — | **NAVEED** | Head of Council · final mandate | Hermes-3 405B |
| hunt | **DROSOPHILA** | Fly-brain market hunter | Qwen2.5 32B (narrates its strikes) |

Every seat runs a **built-in analyst engine** by default (no keys, no network, microseconds
per verdict). Paste an API key in *Settings → LLM Council* and that seat is promoted to a
hosted open-source model through any OpenAI-compatible endpoint (OpenRouter, Together, Groq,
DeepSeek, Mistral, Ollama, custom). Keys are stored on the host machine only.

## NAVEED's advanced training — the CEO outrules the five models

NAVEED is not a sixth voter; he is the one seat **trained** on the advanced trading
curriculum (`backend/soul_exter/llm/ceo_brain.py`) — 26 doctrines across 16 domains
(regime analysis, expectancy, sizing, volatility & the vol surface, portfolio construction,
execution, macro carry, backtest statistics, psychology…). The five cabins each see one
specialty angle; NAVEED holds all of them plus the doctrine layer, and it shows everywhere
he speaks:

* **Rulings** — his executive review (`naveed_synthesis`) reads the five votes *weighted by
  how relevant each desk's specialty is to the ticket's actual numbers* (the vol desk counts
  for more on a top-decile-ATR tape, the trend desk on an efficient one, execution when the
  spread is taxing), then applies the trained overlays: efficiency bands, price-relative ATR
  ("distance is risk"), RSI pullback zones, payoff discipline, playbook evidence, spread tax,
  time stops. Every doctrine he invoked is cited in the ruling, and the mandate carries the
  full management plan (clip · 1×ATR stop · partial at +1.2R · 1.1×ATR trail · time-stop).
* **Answers & chat** — keyless or hosted, his answers quote the doctrine behind the call
  ("From my advanced training — Know the drawdown arithmetic: …"), and his hosted prompts are
  injected with the relevant curriculum for the question at hand.
* **The training record** — he walked into the chat room already at **Market Sage** with an
  `ADV-TRAINED` badge; the five cabins start at Rookie and earn their XP the slow way.

The training is measurable, not cosmetic. `python3 scripts/ceo_study.py` (in `backend/`)
samples tickets off the same calibrated entry gate, walks them to first touch and scores
every desk plus the naive majority on the identical sample. Averaged across seeds the trained
synthesis harvests the most **total R of the whole council** while deploying more capital
than any single cabin, keeps per-ticket expectancy in the top half, and its veto book is the
cleanest on the floor (vetoes land on the losers). The rule bands (efficiency < 0.45 penalises,
ATR > 1.2% of price cuts, RSI < 35 pullbacks press) were calibrated on pooled settled tickets
the same way the floor's other thresholds were (`council_study`, `CALIBRATION.md`).

## The fly-brain connectome — grown neuron by neuron, one racing light

The 3D brain in the **FLY BRAIN** tab is built like the single-neuron confocal
preparations: it is *grown*, not decorated. Each of the ~70 neurons is a branching
arbour (soma → trunk → recursive dendrites) planted in one region — the **left optic
lobe runs pink/red**, the **right optic lobe green**, the **midbrain a red/green/blue
mix** — plus long tract axons bridging optic→central. The veins are thin, dim and
wispy (normal blending — they never shine), soma and tip beads punctuate the arbours,
beaded cortex rings wrap both optic lobes, and a barely-there dark membrane gives the
ghost silhouette on black.

Exactly **one line of light** runs through the veins — fast, continuously, hopping
arbour to arbor. When a desk on the floor **thinks or questions** (cabin hearing,
verdict, CEO ruling, chat Q&A, operator ask), that one line takes the thinker's colour
and sprints harder, then settles back to its quiet run. A fly strike flashes it amber
at triple speed. No thought, no change — the light just keeps racing.

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
5. **Ruling** — five verdicts. **5/5 unanimous** clears the ticket straight to the entry gate —
   a unanimous board needs no executive review. **3–4 approvals** escalate it to the Head of
   Council (cabin 6) with the full record attached: every cabin's verdict, confidence,
   key points, risks and the playbook base rate. **Two approvals or fewer** is an outright veto
   by the cabins — the ticket never reaches the chamber and walks out of the exit door.
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

## View it in a browser tab (localhost)

The interface needs the floor engine, which cannot run in a browser tab on its own — so the
"another tab" path is your own machine, in one command:

```bash
git clone https://github.com/Naserkhan07/soul_exter.git
cd soul_exter
./scripts/run_local.sh          # Windows: .\scripts\run_local.ps1
```

It installs the backend deps, installs and builds the interface, then serves **UI + API + live
feed on one origin**:

```
→  http://localhost:8000          ← open this in any tab, any browser
   http://localhost:8000/docs     ← the REST API explorer
```

Other switches:

```bash
PORT=9000 ./scripts/run_local.sh     # different port
DEV=1     ./scripts/run_local.sh     # hot-reload UI on http://localhost:5173 + API on :8000
```

On `localhost` the page is a secure context, so clipboard, WebGL and the 12 Hz WebSocket all
work without any proxy. If you want hosted LLM desks, put your key in a `.env` at the repo root
(`OPENROUTER_API_KEY=...`) before starting — the script loads it and the Settings → LLM Council
tab will show each desk's running key with a COPY button.

### On a free Kaggle GPU (no local install)

Open `kaggle/soul_exter_kaggle.ipynb` (GPU T4, Internet on) and run the cells: it installs the
two API dependencies, builds the React/three.js interface, optionally runs the track-record
test, starts the floor, and prints a public URL. Nothing is installed on your laptop and no
GPU is used locally.

### Manually, step by step

```bash
# backend
cd backend
pip install -r requirements.txt
python3 -m uvicorn soul_exter.api.server:app --host 0.0.0.0 --port 8000

# interface, dev mode (proxies /api and /ws to the backend)
cd frontend
npm install
npm run dev            # http://localhost:5173

# or build it into the API server (single port, no proxy)
npm run build          # then open http://localhost:8000
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
