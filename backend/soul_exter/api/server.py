"""HTTP + WebSocket surface for the SOUL EXTER floor."""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..agents.schemas import AssetClass
from ..core.engine import FloorEngine
from ..core.layout import layout_payload
from ..core.settings import Settings
from ..llm.client import CLIENT
from ..market.universe import UNIVERSE, by_class, default_enabled

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
STATIC_DIR = os.path.join(APP_DIR, "frontend", "dist")

engine = FloorEngine(Settings.load())
app = FastAPI(title="SOUL EXTER", version="1.0.0",
              description="Autonomous LLM trading council — live floor simulation")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

LAYOUT = layout_payload()


@app.on_event("startup")
async def _startup() -> None:
    await engine.start()


@app.on_event("shutdown")
async def _shutdown() -> None:
    await engine.stop()
    await CLIENT.aclose()


# --------------------------------------------------------------------- REST --
@app.get("/api/health")
async def health() -> dict:
    return dict(ok=True, ts=time.time(), clock=engine.clock, trades=len(engine.trades),
                seats=len(engine.council.seats))


@app.get("/api/layout")
async def layout() -> dict:
    return LAYOUT


@app.get("/api/state")
async def state() -> dict:
    return engine.snapshot(full=True)


@app.get("/api/trades")
async def trades() -> dict:
    return dict(trades=[t.dict() for t in
                        sorted(engine.trades.values(), key=lambda x: x.created_at, reverse=True)],
                outcomes=[o.dict() for o in engine.outcomes[-40:]])


@app.get("/api/trades/{trade_id}")
async def trade_detail(trade_id: str) -> dict:
    d = engine.trade_detail(trade_id)
    if d is None:
        raise HTTPException(404, "unknown trade")
    return d


@app.post("/api/trades/{trade_id}/chat")
async def trade_chat(trade_id: str, payload: dict) -> dict:
    trade = engine.trades.get(trade_id)
    if trade is None:
        raise HTTPException(404, "unknown trade")
    seat_id = str(payload.get("seat_id") or "ceo")
    question = str(payload.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "empty question")
    # route through the floor so the desk answers with the whole book + tape,
    # not just this ticket
    return await engine.ask_desk(seat_id, question, trade_id)


@app.post("/api/chat")
async def desk_chat(payload: dict) -> dict:
    """Ask any desk anything — outside a ticket, any topic. Always answers."""
    seat_id = str(payload.get("seat_id") or payload.get("desk") or "ceo")
    question = str(payload.get("question") or payload.get("q") or "").strip()
    trade_id = payload.get("trade_id")
    if not question:
        raise HTTPException(400, "empty question")
    return await engine.ask_desk(seat_id, question, str(trade_id) if trade_id else None)


from ..llm import keys as keyreg

KEY_FILES, KEY_VALUES = keyreg.load_env_keys()


def host_key_report() -> dict:
    """Which provider keys this host can see (values included: this is the
    operator's own machine, and the Settings panel must be able to show the key
    the desks are running with rather than asking for one again)."""
    out = keyreg.report()
    for provider, info in out.items():
        info["seats"] = [s.id for s in engine.council.seats if s.provider == provider]
    return out


@app.post("/api/trades/{trade_id}/place")
async def place_trade(trade_id: str, patch: dict | None = None) -> dict:
    lots = (patch or {}).get("lots")
    return engine.place_trade(trade_id, float(lots) if lots else None)


@app.post("/api/trades/{trade_id}/book")
async def book_trade(trade_id: str, patch: dict | None = None) -> dict:
    lots = (patch or {}).get("lots")
    return engine.book_trade(trade_id, float(lots) if lots else None)


@app.get("/api/broker")
async def broker() -> dict:
    return dict(broker=engine.broker_status(),
                settings=dict(mode=engine.settings.broker_mode,
                              login=engine.settings.mt5_login,
                              password=engine.settings.mt5_password,
                              server=engine.settings.mt5_server,
                              path=engine.settings.mt5_path,
                              suffix=engine.settings.mt5_symbol_suffix,
                              lots=engine.settings.lots,
                              auto_place=engine.settings.auto_place))


@app.post("/api/broker")
async def broker_save(patch: dict) -> dict:
    engine.apply_settings(patch or {})
    return dict(ok=True, broker=engine.broker_status(),
                settings=dict(mode=engine.settings.broker_mode,
                              login=engine.settings.mt5_login,
                              server=engine.settings.mt5_server,
                              lots=engine.settings.lots,
                              auto_place=engine.settings.auto_place))


@app.get("/api/seats")
async def seats() -> dict:
    rulings = engine.seat_rulings()
    seats_ = []
    for s in engine.council.seats:
        row = s.dict()
        row["ruling"] = rulings.get(s.id)
        seats_.append(row)
    live = [s for s in seats_ if s["live"]]
    return dict(seats=seats_, llm=CLIENT.stats, live_capable=True,
                providers=host_key_report(),
                engine=dict(
                    mode="hosted" if live else "builtin",
                    env_files=KEY_FILES,
                    hosted=[s["name"] for s in live],
                    builtin=[s["name"] for s in seats_ if not s["live"]],
                    note=("All six desks are running the built-in analyst engine — no key needed. "
                          "Paste a key (or export one on the host) to promote a desk to a hosted model."
                          if not live else
                          "Hosted models are answering; the built-in engine remains the fallback."),
                ))


@app.get("/api/desks")
async def desks() -> dict:
    rulings = engine.seat_rulings()
    return dict(desks=[dict(seat=s.dict(), ruling=rulings.get(s.id))
                       for s in engine.council.seats],
                chat_log=dict((k, v[-40:]) for k, v in list(engine.council.chat_log.items())[-6:]))


@app.post("/api/seats/{seat_id}")
async def update_seat(seat_id: str, patch: dict) -> dict:
    seat = engine.council.by_id.get(seat_id)
    if seat is None:
        raise HTTPException(404, "unknown seat")
    for k, v in (patch or {}).items():
        if hasattr(seat, k) and k not in ("id",):
            setattr(seat, k, v)
    engine.settings.set_seats(engine.council.seats)
    engine.settings.save()
    return seat.dict()


@app.post("/api/seats/{seat_id}/test")
async def test_seat(seat_id: str) -> dict:
    seat = engine.council.by_id.get(seat_id)
    if seat is None:
        raise HTTPException(404, "unknown seat")
    if not seat.live():
        return dict(ok=False, mode="builtin",
                    message=f"{seat.name} is running the built-in analyst engine "
                            f"(no provider/key configured). Configure a provider and key to "
                            f"route this cabin to a hosted open-source model.")
    raw = await CLIENT.chat(seat, [dict(role="system", content="You are a trading desk judge. Reply in JSON."),
                                   dict(role="user", content='Reply with {"ok":true,"model":says who you are}')],
                            json_mode=True)
    return dict(ok=raw is not None, mode=seat.provider, model=seat.model,
                message=(raw or CLIENT.stats.get("last_error", "no response"))[:400])


@app.get("/api/universe")
async def universe() -> dict:
    groups: Dict[str, List[dict]] = {}
    for cls in AssetClass:
        groups[cls.value] = [dict(symbol=i.symbol, name=i.name, venue=i.venue,
                                  price=round(i.price, 6), vol=i.vol, spread=i.spread,
                                  enabled=i.symbol in engine.settings.enabled_symbols)
                             for i in by_class(cls.value)]
    return dict(groups=groups, enabled=engine.settings.enabled_symbols,
                defaults=default_enabled(), total=len(UNIVERSE))


@app.get("/api/markets")
async def markets() -> dict:
    return dict(tickers=engine.feed.snapshot(engine.settings.enabled_symbols),
                live=engine.live_status)


@app.get("/api/fly")
async def fly() -> dict:
    return engine.scanner.snapshot()


@app.get("/api/playbook")
async def playbook() -> dict:
    return engine.playbook.snapshot()


@app.get("/api/debate")
async def debate(limit: int = 80) -> dict:
    return dict(messages=engine.council.debate_snapshot(limit),
                lessons=engine.playbook.lessons[-40:])


@app.post("/api/debate/ask")
async def debate_ask(payload: dict) -> dict:
    """Put a question to the debate chamber — answered with live floor context."""
    question = str(payload.get("question") or "").strip()
    seat_id = str(payload.get("seat_id") or "ceo")
    if not question:
        raise HTTPException(400, "empty question")
    seat = engine.council.by_id.get(seat_id, engine.council.by_id.get("ceo"))
    ctx = dict(lessons=engine.playbook.lessons[-6:],
               buckets=engine.playbook.snapshot()["buckets"][:6],
               recent_trades=[t.dict() for t in list(engine.trades.values())[-6:]],
               markets=engine.feed.snapshot(engine.settings.enabled_symbols[:8]),
               topic=question)
    msg = engine.council.debate_turn(ctx)
    msg["text"] = f"Question from the floor: {question} — " + msg["text"]
    msg["kind"] = "question"
    engine.emit("debate", message=msg)
    return msg


@app.get("/api/settings")
async def get_settings() -> dict:
    return dict(settings=engine.settings.dict(),
                seats=[s.dict() for s in engine.council.seats],
                universe_size=len(UNIVERSE))


@app.post("/api/settings")
async def post_settings(patch: dict) -> dict:
    engine.apply_settings(patch or {})
    return dict(settings=engine.settings.dict())


@app.post("/api/control")
async def control(patch: dict) -> dict:
    action = str((patch or {}).get("action", ""))
    if action == "pause":
        engine.settings.paused = True
    elif action == "resume":
        engine.settings.paused = False
    elif action == "reset":
        engine.reset()
    elif action == "strike":
        trade = engine.force_strike(patch.get("symbol"))
        return dict(ok=trade is not None, trade=trade.dict() if trade else None)
    elif action == "speed":
        engine.settings.speed = float(patch.get("value", 1.0))
    engine.settings.save()
    return dict(ok=True, paused=engine.settings.paused, speed=engine.settings.speed)


@app.get("/api/analytics")
async def analytics() -> dict:
    from ..llm.expectancy import model_meta
    accepted = [t for t in engine.trades.values() if t.outcome == "accepted" and t.pnl_r]
    vetoed = [t for t in engine.trades.values() if t.outcome == "rejected" and t.cf_r]
    return dict(stats=engine.stats, playbook=engine.playbook.snapshot(),
                outcomes=[o.dict() for o in engine.outcomes[-60:]],
                fly=engine.scanner.agent.snapshot(),
                llm=CLIENT.stats, model=model_meta(),
                book=dict(
                    accepted=len(accepted),
                    accepted_r=round(sum(t.pnl_r for t in accepted), 2),
                    accepted_mean=round(sum(t.pnl_r for t in accepted) / len(accepted), 3) if accepted else 0.0,
                    vetoed=len(vetoed),
                    veto_saved_r=round(sum(t.cf_r for t in vetoed), 2),
                    veto_mean=round(sum(t.cf_r for t in vetoed) / len(vetoed), 3) if vetoed else 0.0,
                ))


# ----------------------------------------------------------------------- WS --
class Hub:
    def __init__(self) -> None:
        self.clients: List[WebSocket] = []

    async def send(self, ws: WebSocket, payload: dict) -> bool:
        try:
            await ws.send_text(json.dumps(payload, separators=(",", ":"), default=str))
            return True
        except Exception:
            return False


hub = Hub()


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    hub.clients.append(ws)
    try:
        await ws.send_text(json.dumps(dict(type="hello", layout=LAYOUT,
                                           settings=engine.settings.dict(),
                                           seats=[s.dict() for s in engine.council.seats],
                                           universe=dict(total=len(UNIVERSE),
                                                          enabled=engine.settings.enabled_symbols),
                                           server_ts=time.time()), default=str))
        while True:
            # keep the socket alive; real data is pushed by the broadcaster
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text(json.dumps(dict(type="pong", ts=time.time())))
            else:
                try:
                    data = json.loads(msg)
                except Exception:
                    continue
                if data.get("type") == "chat":
                    trade = engine.trades.get(str(data.get("trade_id")))
                    question = str(data.get("question") or "").strip()
                    if question:
                        res = await engine.ask_desk(str(data.get("seat_id") or "ceo"), question,
                                                    trade.id if trade else None)
                        await ws.send_text(json.dumps(dict(type="chat_reply",
                                                           trade_id=(trade.id if trade else None),
                                                           payload=res), default=str))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if ws in hub.clients:
            hub.clients.remove(ws)


async def broadcaster() -> None:
    """Push state frames + events to every connected browser."""
    frame_interval = 1.0 / 12.0
    while True:
        await asyncio.sleep(frame_interval)
        if not hub.clients:
            engine.drain_events()
            continue
        events = engine.drain_events(80)
        payload = dict(type="frame", t=time.time(), clock=round(engine.clock, 2),
                       stats=engine.stats, fly=engine.scanner.agent.snapshot(),
                       walkers=engine.walker_payload(),
                       trades=[t.dict() for t in
                               sorted(engine.trades.values(), key=lambda x: x.created_at,
                                      reverse=True)[:24]],
                       counts={}, markets=engine.feed.snapshot(engine.settings.enabled_symbols[:18]),
                       events=events, paused=engine.settings.paused, speed=engine.settings.speed)
        dead = []
        for ws in list(hub.clients):
            ok = await hub.send(ws, payload)
            if not ok:
                dead.append(ws)
        for ws in dead:
            if ws in hub.clients:
                hub.clients.remove(ws)


@app.on_event("startup")
async def _start_broadcaster() -> None:
    asyncio.create_task(broadcaster())


# ---------------------------------------------------------------- static app --
if os.path.isdir(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/")
    async def index() -> Any:
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @app.get("/{path:path}")
    async def spa(path: str) -> Any:
        full = os.path.join(STATIC_DIR, path)
        if os.path.isfile(full):
            return FileResponse(full)
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
