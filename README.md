# SOUL EXTER — an LLM trading floor

![the floor](docs/floor-preview.png)

A trading floor you can watch. Dozens of traders sit at desks — each one is a trade the scanner
found. Five glass cabins hold **five different open-source LLMs**, one per risk discipline. Every
trade walks from cabin to cabin, collecting verdicts, until it either takes the **entry door**
(approved), the **exit door** (rejected), or gets escalated to the **CEO cabin** — a sixth, larger
LLM that owns the final call.

**No API keys. No paid endpoints. All weights are open and ungated** (they download anonymously).

```
             ┌──────────┐     ┌──────────── the council ────────────┐
  live tape  │ scanner  │     │  QUANT   RISK   NEWS   MACRO   COMPL.│        CEO
  ──────────▶│ 5 setups │────▶│  Qwen     Mistral Zephyr Qwen    Phi │──────▶ Qwen-14B ──▶ ENTRY / EXIT
             └────┬─────┘     │  7B       7B      7B     3B      mini │        (only if the council splits)
                  │           └──────────────────────────────────────┘
             ┌────▼─────┐
             │  SCOUT   │  a spiking FlyWire-style brain (12k synapses) that reads the same
             │ fly brain│  features and answers CONFIRM / WAIT / CONTRADICT. Only what it
             └──────────┘  confirms is worth the council's time — and it learns from P&L.
```

---

## The rules of the floor

| Council result | Where the trader goes |
|---|---|
| **5 of 5 approve** | straight through the **entry door** → a paper position is opened |
| **0 of 5 approve** | straight out the **exit door** |
| **1–4 approve** (a split) | up to the **CEO cabin**; the CEO reads all five verdicts and decides the door |

Every cabin returns more than a yes/no: a **confidence %**, **risk flags**, and a **size
multiplier**. So a desk can say *"approve, but at half size, and watch the spread"* — and the paper
desk actually opens the position at half size.

Each cabin sees the trade packet (entry, stop, target, R:R, strategy, full feature set), the live
market read, the current book, **and the verdicts of the cabins before it**. The CEO sees the whole
transcript plus the tally.

### Two things worth knowing up front

**1. Wave mode is on by default.** On a T4, five cabins answering back-to-back takes 2–3 minutes per
trade. Instead the cabins run in two waves:

- wave 1: QUANT, RISK, NEWS — in parallel, each reasoning independently
- wave 2: MACRO, COMPLIANCE — in parallel, both reading all three wave-1 verdicts
- then the CEO

That is ~3× faster, and each cabin still sees every *earlier stage*. The trade-off: cabins in the
same wave cannot see each other. If you want the strict sequence
`QUANT → RISK → NEWS → MACRO → COMPLIANCE → CEO` where every cabin reads all of its predecessors,
set `SOUL_WAVE_MODE=0`. Both modes are covered by tests.

**2. It is a paper desk.** Positions are simulated against real prices, with real risk rules
(0.75% of equity risked per trade, 3% session risk cap, no leverage, max 8 open). Nothing is sent to
an exchange.

---

## Quick start (local, no GPU)

The pipeline is real; only the model weights are replaced by deterministic persona brains.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
SOUL_MOCK_LLM=1 python -m soul
# open http://localhost:8000
```

You get the full floor: scanner → 5 cabins → CEO → doors → paper P&L, with a live 3D view.

> Point a tunnel at it if you want to watch from your phone: `cloudflared tunnel --url http://localhost:8000`

## Running it on a free Kaggle GPU

**That is the intended deployment.** The notebook is `kaggle/soul_exter_kaggle.ipynb`.

1. Kaggle → *Create → Notebook* → **Settings → Accelerator → GPU T4 x2** and **Internet → On**.
2. Upload/import the notebook from this repo and run the cells in order.
3. Cell 5 prints a public `https://…trycloudflare.com` URL. Open it — that is your floor, served
   from Kaggle, with the websocket stream intact. Your laptop runs nothing.

First run downloads ~25 GB of weights into `/kaggle/working/hf` (kept across saves if you commit the
notebook output). Roughly 10–15 minutes, then the cabins start filling.

### Model roster

Every model below is **ungated** — `huggingface_hub` can fetch it with no token and no license
click. That is why there is no Llama and no Gemma in the list (both require an account + terms).

| cabin | model | 4-bit size | license |
|---|---|---|---|
| QUANT | `Qwen/Qwen2.5-7B-Instruct` | ~5.0 GB | Apache-2.0 |
| RISK | `mistralai/Mistral-7B-Instruct-v0.3` | ~5.0 GB | Apache-2.0 |
| NEWS | `HuggingFaceH4/zephyr-7b-beta` | ~5.0 GB | MIT |
| MACRO | `microsoft/Phi-3.5-mini-instruct` | ~2.6 GB | MIT |
| COMPLIANCE | `Qwen/Qwen2.5-3B-Instruct` | ~2.4 GB | Apache-2.0 |
| **CEO** | `Qwen/Qwen2.5-14B-Instruct` | ~9.5 GB | Apache-2.0 |

Six desks, six *different* sets of weights: the head of desk never decides a
trade on the same model that voted on it. (`SOUL_MODEL_PROFILE=variety` keeps
the same six models but gives the macro desk the 7B reasoner and drops quant to
the 3B; `low` is the laptop profile and shares two small models on purpose.)

2 × T4 = 32 GB, and the pool keeps the most recently used models resident
(`SOUL_MODEL_CACHE`, default 6). Profiles: `SOUL_MODEL_PROFILE=low|standard|variety`.

### Training the desks

A desk is not a static prompt. Three things train it, in this order of immediacy:

1. **The curriculum** — the house playbook and the desk's own schooling (`soul/knowledge.py`).
   It is in every system prompt, and the ten seed lessons are read back into every verdict as
   DESK MEMORY from the first trade of a session, so a desk on its first trade is not a desk
   with nothing on file.
2. **The room** — every debate round ends with a rule the head of desk writes down
   (`soul/debate.py`), and those rules go back into the next prompt. The desks teach each
   other in context, and the rules are visible in the Chat room.
3. **The record** — every settled decision becomes supervised data (`soul/training.py`): the
   exact packet the desk was shown, the verdict it gave, and what that decision was worth
   when the position closed. That dataset is exported as chat JSONL and turned into a LoRA
   adapter per desk:

```bash
python -m soul.train --dataset-only        # just build artifacts/training/desk-sft.jsonl
python -m soul.train --desks all --epochs 2   # LoRA per desk (needs a GPU + transformers/peft)
```

```bash
curl -s localhost:8000/api/training        # rows per desk, and whether an adapter exists
curl -s localhost:8000/api/training/dataset > session-sft.jsonl   # the dataset itself
```

You can *watch* all of this happen. The chat room (top bar → **Chat room**) is where the six
desks talk, and its turns are labelled by what they are doing for the training:

| turn | who | what it is |
|---|---|---|
| `claim` (↺ recalled) | the desk that opens the round | names the rule already on file that bears on the topic, then argues under it |
| `challenge` / `question` / `answer` / `ack` | the desks | the argument itself, addressed to a named desk |
| `lesson` (★) | the head of desk | writes this round's rule — the one that feeds every later prompt |
| `carry` (↺ carried) | two desks, rotating | what *that desk* will do differently tomorrow because of the rule |
| `postmortem` (▲ after the close) | a desk that was on the wrong side | reviews the closed position and says what it learned |

Press **training turns** in the room to read only that channel — recalled, written, carried,
reviewed — which is the honest answer to "are they learning, or just talking?". The same
turns are what becomes the dataset below. `docs/training-sample.md` has real examples.

The loop is symmetric on purpose: a desk that **approved a loser** is trained on *its own risk
flags* as the reason to refuse, a desk that **refused a winner** is trained on the same objection
at half size, and a desk that refused a loser is rewarded exactly like one that approved a winner.
Nothing in it teaches "always approve" or "always refuse". Put the trained adapters in
`artifacts/adapters/<DESK>/` (or set `SOUL_ADAPTERS`) and the local-HF backend loads each desk's
own adapter on top of its own base weights — QUANT and RISK stop being the same model in two hats.
Guarded by `tests/test_training.py`.

A CPU-only box cannot train and does not pretend to: `python -m soul.train` writes the dataset,
prints exactly which packages are missing, and exits 0. The floor still runs (mock personas), so
the rest of the pipeline stays testable.

---

## Placing trades — the scanned list, one click, and MetaTrader 5

Every trade the six desks rule on lands in an **execution panel**: the *scanned* list on the left,
the *placed* book on the right. One click on **Place trade** sends it; one click on
**Close trade** books it at market, immediately.

A row carries everything you need to decide by hand: the pair and its full name (EUR/USD · *Euro /
US Dollar*), the direction, the six desks' own votes (hover a chip for that desk's one-line reason),
the confidence, entry / stop / target, R:R, and the size that the stop implies. The size is not a
guess — it is `risk % of the account ÷ (stop in pips × value of a pip per lot)`, re-derived from the
price the venue is quoting at the moment you click, so a signal that has aged does not quietly
double the money it is risking.

### Where an order goes

| asset class | venue | why |
|---|---|---|
| **forex, metals** | **your MetaTrader 5 terminal** | the account you already trade |
| crypto | paper venue | Binance public data is keyless, but there is no broker wired yet |
| indices, stocks, futures, options | paper venue | no broker named yet — tell me which one |

The routing is printed on every row, and it never lies: if a class is pinned to the terminal and the
terminal is not connected, the order is **refused with the reason** rather than quietly filled on
paper. `FOREX` and `MT5` badges are on the row, the panel header and the settings drawer.

### Connecting the terminal

MT5's Python API needs the terminal running on the same machine (Windows, or Linux via the
`mt5linux` bridge). Put the login in **Settings → Broker**: login, password, server
(`MetaQuotes-Demo`), and a venue mode — `auto` (terminal when it answers, paper otherwise), `mt5`
(pinned: refuse rather than fall back), or `paper` (never touch the terminal).

```bash
pip install MetaTrader5            # Windows, with the terminal installed and logged in
# ...or, from Linux/macOS against a terminal on another box (wine):
SOUL_MT5_BRIDGE=192.168.1.20:18812 python -m soul
```

The login is stored in `artifacts/broker/mt5.json` — **inside the gitignored tree**, mode `0600`.
The password is never returned by the API (the response carries `••••••••`), never logged, and never
rendered into the page. *Forget login* deletes the file.

### Automatic placement

Arming **auto-place approved** sends every trade the council approves, in the classes you tick, at
the risk you set — so forex approvals can go to the terminal without a click, with a confidence
floor, a maximum number of live orders, and the same one-order-per-pair rule. It is **off** until
you arm it: `SOUL_AUTOTRADE=1 SOUL_AUTOTRADE_CLASSES=forex` sets the default.

```bash
export SOUL_MT5_LOGIN=112594843
export SOUL_MT5_PASSWORD=...       # never committed: read from the environment or the local store
export SOUL_MT5_SERVER=MetaQuotes-Demo
export SOUL_BROKER_RISK_PCT=0.5    # % of the broker account risked per order
export SOUL_AUTOTRADE=1 SOUL_AUTOTRADE_CLASSES=forex
python -m soul
```

What the terminal gets: a market order with the stop and target attached (`SL`/`TP` in the request),
sized to the broker's own `volume_min`/`volume_step`, with the filling mode falling back
IOC → FOK → RETURN (retcode `10030` is almost always this), the broker's symbol suffix resolved
(`EURUSD` → `EURUSD.a` / `EURUSDm` / `EURUSD.raw`), and a close that is verified against
`positions_get` instead of assumed. Every refusal is a sentence, not a stack trace.

> **No terminal, no lies.** On this sandbox and on Kaggle there is no MetaTrader 5 terminal, so the
> panel says `paper venue` and the routing line says why. The exchange tokens that *would* be needed
> for real crypto are exactly the API keys this project refuses to hold.

---

## Configuration

Everything is an environment variable; nothing else needs editing.

**Floor behaviour**

| variable | default | meaning |
|---|---|---|
| `SOUL_MOCK_LLM` | auto | `1` forces the synthetic personas. Auto-detects: no CUDA → mock |
| `SOUL_WAVE_MODE` | `1` | `0` = strictly sequential cabins (every cabin reads all predecessors) |
| `SOUL_SCAN_SECONDS` | `25` | how often the scanner looks for setups |
| `SOUL_MIN_SCORE` | `0.28` | scanner conviction threshold (0–1) |
| `SOUL_MAX_CANDIDATES` | `3` | trades per scan |
| `SOUL_MAX_IN_FLIGHT` | `6` | trades allowed on the floor at once |
| `SOUL_TRADE_COOLDOWN` | `420` | don't re-review the same symbol+side+strategy for N seconds |
| `SOUL_DESKS` | `64` | desk count on the floor (cosmetic) |

**Models**

| variable | default | meaning |
|---|---|---|
| `SOUL_MODEL_PROFILE` | `standard` | `low` / `standard` / `variety` |
| `SOUL_LOAD_4BIT` | `1` | bitsandbytes NF4 quantisation |
| `SOUL_MODEL_CACHE` | `6` | how many models stay in VRAM |
| `SOUL_LLM_CONCURRENCY` | `3` | cabins generating at the same time |

**Desk / risk**

| variable | default | meaning |
|---|---|---|
| `SOUL_STARTING_CASH` | `15000` | paper equity |
| `SOUL_RISK_PCT` | `0.75` | % of equity risked per trade |
| `SOUL_SESSION_RISK_PCT` | `3.0` | cap on total open risk |
| `SOUL_MAX_OPEN` | `8` | max concurrent positions |
| `SOUL_MAX_LEVERAGE` | `1.0` | 1.0 = spot, no leverage |

**Market data**

| variable | default | meaning |
|---|---|---|
| `SOUL_MARKET_SOURCE` | `auto` | `auto` / `ccxt` (live public Binance) / `sim` |
| `SOUL_VENUE` | `binance` | any ccxt exchange with public endpoints |
| `SOUL_TIMEFRAME` | `5m` | candle timeframe |
| `SOUL_SIM_BAR_SECONDS` | `8` | simulator: wall-clock seconds per simulated 5m bar |

Live data uses ccxt against public REST endpoints — **no API key, ever**. If Kaggle has no internet
(or ccxt is missing), `auto` falls back to the built-in correlated simulator and the badge in the UI
tells you which is running.

---

## What is on screen

The interface is a React + TypeScript app (`frontend/`) drawn over a full-bleed isometric canvas.
Every pixel of the room comes from the engine's event stream; the UI holds no trading logic.

- **The floor** — three blocks of desks on a travertine floor, each occupied desk carrying a trader
  with **the pair it is trading written above its head**, plus the fly scout's read of that setup.
- **The five cabins + CEO** — glass control rooms on an elevated deck, reached by a staircase. Each
  cabin shows its model name, `DELIBERATING` while it reasons, then its verdict chip and confidence.
- **The doors** — lit **WELCOME** (entry) and **EXIT** portals on the front edge, with a check-in
  desk beside the entry; trades walk in through one and out through the other.
- **Panels** — the council rail (per-cabin state), the **fly scout** panel (neurons, synapses,
  judged / confirmed / waited / contradicted, admit rate, rewards, last batch), the equity spark,
  the book (open positions with live P&L and closes), the market tape and the trade record.
- **Execution panel** — the scanned list (every trade the six desks ruled on, with *their six
  votes*, the pair name, the stop and the size it implies) beside the **placed** book, where each
  live order shows its live P&L, its ticket, and a **Close trade** button that books it immediately.
  `MT5` / `PAPER` is printed on every row. `⤢` opens it over the floor.
- **Trade drawer** — click any row or trader for the full audit: the scout's read, the market
  snapshot the trade came from, all five cabin verdicts (model, confidence, reason, flags,
  latency and sizing adjustment), the CEO's ruling when it was escalated, and the risk block.

![cabins](docs/cabin-closeup.png)

Above: the cabins mid-session. A trade walks into the cabin it is being judged in, not just up to
its door — the visitor stands inside the glass next to the desk that is ruling on it:

![a visitor inside a cabin](docs/visitor-in-cabin.png)

Below: the whole floor, with the ticker wall, the march of desks and the scout drone patrolling the
aisle.

![the floor](docs/floor-preview.png)

The room is verified without a browser: `tools/floor_smoke.ts` steps the animation and dumps the
renderer's drawing ops, `tools/render_floor.py` rasterises them to PNG, and `tools/ui_smoke.mjs`
mounts the real React bundle in a DOM (fixture **or** live server) and asserts the panels render.

---

## HTTP API

| method | path | purpose |
|---|---|---|
| `GET` | `/` | the floor |
| `GET` | `/api/state` | full snapshot (engine, market, council, desk, positions, roster) |
| `GET` | `/api/training` | training rows per desk, and whether an adapter has been trained |
| `POST` | `/api/training/build` | write the supervised dataset to `artifacts/training/` |
| `GET` | `/api/training/dataset` | the dataset itself, as chat JSONL |
| `GET` | `/api/trades` | audit log of every trade the floor has seen |
| `GET` | `/api/trades/{id}` | full council transcript for one trade |
| `POST` | `/api/scan` | force a scan now |
| `POST` | `/api/control` | `{paused, scan_seconds, min_score, max_candidates}` |
| `POST` | `/api/demo/seed` | `{count}` push candidates straight onto the floor |
| `POST` | `/api/demo/shock` | inject volatility into the tape |
| `POST` | `/api/desk/close-all` | flatten the paper book |
| `GET` | `/api/signals` | every scanned trade with the six desks' votes, price, size and venue |
| `GET` | `/api/broker` | venue, account, routing by asset class, auto-trade state (login masked) |
| `POST` | `/api/broker/connect` | `{login, password, server, mode}` — connect the MT5 terminal |
| `POST` | `/api/broker/disconnect` | `{forget}` — drop the connection, or delete the stored login |
| `POST` | `/api/broker/size` | `{signal_id, risk_pct}` — what that trade would cost |
| `POST` | `/api/broker/place` | `{signal_id, risk_pct, volume}` — **one click: place it** |
| `POST` | `/api/broker/close` | `{ticket}` — **one click: book it, now** |
| `POST` | `/api/broker/close-all` | flatten everything the broker is holding |
| `POST` | `/api/broker/autotrade` | `{on, classes, risk_pct, max_open, min_confidence}` |
| `WS` | `/ws` | realtime event stream (the UI falls back to SSE, then polling) |

---

## Project layout

```
soul/
  config.py        env-driven configuration + the vote rules
  models.py        TradeCandidate, Verdict, CouncilResult, Position
  market.py        ccxt public data + offline correlated simulator
  scanner.py       5 numpy strategies, shared feature block, scoring, cooldowns
  flybrain.py      spiking FlyWire-inspired screen (ORN→LN→PN→KC→MBON, 12k synapses)
  scout.py         the scout: gates and ranks candidates, learns from realised P&L
  council.py       the five cabins, wave scheduling, CEO escalation
  knowledge.py     the house playbook, per-desk schooling, the seed lessons
  training.py      the supervised dataset: curriculum, room rules, settled decisions
  train.py         `python -m soul.train` — LoRA fine-tune per desk, no API keys
  desk.py          paper fills, sizing, stops/targets, P&L
  engine.py        wires it together and publishes events
  api.py           FastAPI + websocket + SSE
  bus.py           async pub/sub
  brains/
    base.py        cabin personas, prompt construction, verdict parsing
    local_hf.py    4-bit transformers models on GPU  (Kaggle path)
    mock.py        deterministic persona brains      (no-GPU path)
frontend/
  index.html       HUD shell (splash, theme, mount point)
  src/floor/       isometric renderer: layout, geometry, actors, room, scene
  src/state/       useSoul(): WS → SSE → polling transport, wire-shape normalising
  src/components/  panels, trade drawer, canvas host
  src/styles/      the control-room theme
web/               build output served by the API (index.html, assets/app.js, assets/app.css)
kaggle/
  soul_exter_kaggle.ipynb   the whole thing, cells in order
tools/
  floor_smoke.ts   headless floor harness: steps frames, dumps drawing ops
  render_floor.py  rasterise those ops to a PNG
  ui_smoke.mjs     mount the built UI in a DOM, check the panels (use --live for a real server)
  eval_scout.py    does the fly scout actually pick winners? (measured, not asserted)
  tune_mock.py     calibrate the mock personas
  tune_flybrain.py calibrate the spiking network
tests/
  test_council.py  routing, parsing, prompts, cabins, desk, calibration
  test_roster.py   six desks, six different models, all ungated
  test_training.py the curriculum, the settled-decision labels, the adapters
```

## Tests

```bash
python -m pytest tests/ -q                     # 29 tests: routing, parsing, desk, calibration
node tools/ui_smoke.mjs                        # builds the UI and checks it against a fixture
node tools/ui_smoke.mjs --live http://127.0.0.1:8000    # …and against a running server
node tools/tune_flybrain.py                    # firing rates, sparsity, decision spread
python tools/eval_scout.py --seeds 4 --bars 1000        # the scout's gate, measured
cd frontend && npx esbuild ../tools/floor_smoke.ts --bundle --platform=node --format=esm \
  --outfile=/tmp/smoke.mjs && node /tmp/smoke.mjs /tmp/f.json --focus all && \
  python tools/render_floor.py /tmp/f.json floor.png
```

There is no browser in the build environment, so the UI is verified in two layers: the renderer is
measured as a list of drawing ops (which the Python rasteriser turns into the PNG above), and the
React tree is mounted in jsdom and asserted against the payload a real server returns.

### Does the scout actually help?

`tools/eval_scout.py` answers that with the simulator as ground truth: generate regime-switching
paths, run the real strategies bar by bar, label every candidate by walking the price forward until
it hits its stop, target or horizon, then ask the fly for its verdict. Over ~46,000 candidates:

| what the gate admits | kept | hit rate | mean P&L |
|---|---|---|---|
| everything the scanner found | 46,000 | 35.6% | +0.19% |
| fly confirms (z ≥ 0.0) | 10,741 | 37.8% | +0.28% |
| fly confirms (z ≥ 0.8, default) | 6,368 | **39.9%** | **+0.38%** |
| fly confirms (z ≥ 1.3) | 2,166 | 40.8% | +0.41% |

The lift is monotone in the fly's confidence and survives every seed set tried; the default gate sits
at the knee of that curve (nearly all the quality, three times the flow). Read it for what it is: a
better filter over a mediocre signal, not an edge — the scanner is still the thing being filtered.

## Honest limitations

- The scanner is a compact, readable quant stack — five classic strategies. It is the *subject* of
  the floor, not a proven edge. Two of them (mean reversion, trend pullback) lose money on the
  simulator outright, and the council is what is supposed to refuse them.
- The fly scout's lift (35.6% → 39.9% hit rate) is measured **on the simulator**, which is where its
  labels come from. It is a real, reproducible improvement in candidate selection; it is not
  evidence of live profitability.
- The default local run uses mock brains, so what you see locally is the *plumbing*: state machine,
  doors, walk animations, panels. The reasoning is only real on the Kaggle GPU path.
- A T4 generates ~10–25 tokens/second on a 7B model. Cabins answering in parallel gets you roughly
  **1–3 completed trades per minute**; strictly sequential mode is 3–4× slower.
- The CEO is one model reading a transcript, not a committee of one — it can still be wrong.
- Real exit liquidity, fees and slippage are only approximated (a spread proxy and an ATR-based
  stop); the paper fills are optimistic.
- **The live path is written, not witnessed.** This sandbox has no MetaTrader 5 terminal and no
  network route to a broker, so what is tested here is every part of the order flow except the last
  hop: sizing, routing, refusal reasons, one-order-per-pair, the paper fills, the one-click place
  and the one-click close. The MT5 adapter follows the documented API (`order_send`,
  `positions_get`, `symbol_info`) and handles the usual failure modes, but the first live fill is
  yours to watch. Start on a **demo** account — the login you enter is a demo server.
- Auto-trade is off by default for a reason. Arming it means a language model can open positions in
  your account without asking. Set the risk percentage and the class list first, and keep a
  kill-switch (pause the floor, or `close-all`) within reach.
- Not financial advice. Do not wire this to real money without doing the work on the scanner, the
  sizing and the kill-switch yourself.
