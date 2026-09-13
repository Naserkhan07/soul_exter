"""HTTP + WebSocket surface.

    GET  /                     the 3D trading floor
    GET  /api/state            full snapshot (also used as a polling fallback)
    GET  /api/trades           audit log of every trade the floor has seen
    GET  /api/trades/{id}      full council transcript for one trade
    POST /api/scan             force a scan now
    POST /api/control          pause / tune scanning live
    POST /api/demo/seed        push N candidates straight onto the floor
    POST /api/demo/shock       inject volatility
    POST /api/desk/close-all   flatten the paper book
    WS   /ws                   realtime event stream
    GET  /api/stream           same stream as SSE (proxy-friendly fallback)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import universe as book
from .bus import EventBus
from .config import Config, load_config
from .engine import Engine

log = logging.getLogger("soul.api")


class ControlPayload(BaseModel):
    paused: Optional[bool] = None
    scan_seconds: Optional[float] = None
    min_score: Optional[float] = None
    max_candidates: Optional[int] = None


class SeedPayload(BaseModel):
    count: int = 3


class InstrumentsPayload(BaseModel):
    """Which markets the desk is allowed to trade.

    The panel sends the full set of ticked symbols; anything the catalogue does
    not know is dropped rather than trusted, so a stale client cannot quietly
    widen the book.
    """

    symbols: list[str] = []


class DebatePayload(BaseModel):
    rounds: int = 1
    topic: Optional[str] = None


class AskPayload(BaseModel):
    """A question aimed at one desk about one trade."""
    cabin: str
    question: str
    trade_id: Optional[str] = None


def create_app(cfg: Optional[Config] = None) -> FastAPI:
    cfg = cfg or load_config()
    bus = EventBus()
    engine = Engine(cfg, bus)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await engine.start()
        log.info("SOUL EXTER up — floor open (mode=%s)", engine.llm_mode)
        try:
            yield
        finally:
            await engine.stop()

    app = FastAPI(title="SOUL EXTER — LLM Trading Floor", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_credentials=False,
        allow_methods=["*"], allow_headers=["*"],
    )
    app.state.engine = engine
    app.state.bus = bus
    app.state.cfg = cfg

    web_dir = os.path.abspath(cfg.web_dir)
    if os.path.isdir(web_dir):
        app.mount("/static", StaticFiles(directory=web_dir), name="static")

    # ------------------------------------------------------------------
    # endpoints
    # ------------------------------------------------------------------
    @app.get("/api/health")
    async def health() -> Dict[str, Any]:
        return {"ok": True, "llm_mode": engine.llm_mode, "market": engine.market.mode,
                "uptime_s": round(engine.state()["engine"]["uptime_s"], 1)}

    @app.get("/api/state")
    async def state() -> Dict[str, Any]:
        return engine.state()

    @app.get("/api/trades")
    async def trades(limit: int = 60) -> Dict[str, Any]:
        return {"count": len(engine.trade_log), "trades": engine.trade_log[-limit:][::-1]}

    @app.get("/api/trades/{trade_id}")
    async def trade_detail(trade_id: str) -> Dict[str, Any]:
        if engine.council:
            found = engine.council.get(trade_id)
            if found:
                return found
        for t in reversed(engine.trade_log):
            if t["trade_id"] == trade_id:
                return t
        raise HTTPException(status_code=404, detail="unknown trade")

    @app.get("/api/settings")
    async def settings() -> Dict[str, Any]:
        """Everything the settings drawer draws: the model roster and the book.

        Note what is *not* here: there is no API key field, no token, no
        endpoint credential — the roster runs on local weights, and the market
        sources are keyless. `key_required: false` is the whole point of the
        design, so the panel shows model ids and backends instead of secrets.
        """
        return {
            "roster": [
                {
                    "key": r["key"], "name": r.get("name", r["label"]),
                    "title": r.get("title", r["role"]), "role": r["role"],
                    "is_ceo": r["is_ceo"], "slot": r["slot"], "model": r["model"],
                    "backend": r["backend"], "temperature": r["temperature"],
                    "expertise": r.get("expertise", []), "style": r.get("style", ""),
                    "key_required": False, "auth": r.get("auth", "none"),
                    "license": r.get("license", "open weights"),
                }
                for r in engine.registry.values()
            ],
            "instruments": book.catalogue(engine.market.source_of),
            "selected": list(engine.cfg.universe),
            "debate": {
                "enabled": engine.debate is not None,
                "rounds": engine.debate.rounds if engine.debate else 0,
                "seconds": engine.cfg.debate_seconds,
            },
            "engine": {
                "llm_mode": engine.llm_mode,
                "model_profile": engine.cfg.model_profile,
                "market_mode": engine.market.mode,
                "desks": engine.cfg.desks,
            },
        }

    @app.post("/api/settings/instruments")
    async def set_instruments(payload: InstrumentsPayload) -> Dict[str, Any]:
        chosen = await engine.set_instruments(payload.symbols)
        return {"ok": True, "selected": chosen, "count": len(chosen),
                "classes": book.classes_of(chosen)}

    @app.get("/api/debate")
    async def debate(limit: int = 40) -> Dict[str, Any]:
        if engine.debate is None:
            return {"enabled": False, "transcript": [], "lessons": []}
        snap = engine.debate.snapshot()
        snap["transcript"] = snap["transcript"][-max(1, min(200, limit)):]
        return {"enabled": True, **snap}

    @app.post("/api/debate/round")
    async def debate_round(payload: DebatePayload) -> Dict[str, Any]:
        """Hold a review meeting now — used by the UI's 'convene' button."""
        if engine.debate is None:
            raise HTTPException(status_code=409, detail="debate disabled")
        topic = {"topic": payload.topic, "inner": {}, "trade_id": None} if payload.topic else None
        said = []
        for _ in range(max(1, min(3, payload.rounds))):
            said = await engine.debate.run_round(topic)
            topic = None
        return {"ok": True, "turns": len(said), "rounds": engine.debate.rounds,
                "topic": engine.debate.current_topic, "said": said}

    @app.post("/api/debate/ask")
    async def debate_ask(payload: AskPayload) -> Dict[str, Any]:
        """Ask a cabin why it agreed or disagreed. The cabin answers in the room."""
        if engine.debate is None:
            raise HTTPException(status_code=409, detail="debate disabled")
        msg = await engine.ask_desk(payload.cabin, payload.question, payload.trade_id)
        if msg is None:
            raise HTTPException(status_code=404, detail=f"no such desk: {payload.cabin}")
        return {"ok": True, "said": msg, "rounds": engine.debate.rounds}

    @app.post("/api/scan")
    async def force_scan() -> Dict[str, Any]:
        found = await engine.run_scan(force=True)
        return {"found": len(found), "symbols": [c.symbol for c in found]}

    @app.post("/api/control")
    async def control(payload: ControlPayload) -> Dict[str, Any]:
        if payload.paused is not None:
            engine.paused = payload.paused
        if payload.scan_seconds is not None:
            engine.scan_seconds = max(3.0, float(payload.scan_seconds))
        if payload.min_score is not None:
            engine.min_score = min(1.0, max(0.0, float(payload.min_score)))
            engine.cfg.min_score = engine.min_score
        if payload.max_candidates is not None:
            engine.cfg.max_candidates_per_scan = max(1, min(8, int(payload.max_candidates)))
        await bus.publish("control", paused=engine.paused, scan_seconds=engine.scan_seconds,
                          min_score=round(engine.min_score, 3))
        return {"ok": True, "paused": engine.paused, "scan_seconds": engine.scan_seconds,
                "min_score": engine.min_score}

    @app.post("/api/demo/seed")
    async def demo_seed(payload: SeedPayload) -> Dict[str, Any]:
        n = max(1, min(12, payload.count))
        await engine.seed_demo(n)
        return {"ok": True, "queued": n}

    @app.post("/api/demo/shock")
    async def demo_shock() -> Dict[str, Any]:
        await engine.inject_volatility()
        return {"ok": True}

    @app.post("/api/desk/close-all")
    async def close_all() -> Dict[str, Any]:
        n = await engine.close_all()
        return {"ok": True, "closed": n}

    # ------------------------------------------------------------------
    # realtime
    # ------------------------------------------------------------------
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        queue = bus.subscribe()
        try:
            await ws.send_text(json.dumps({"type": "hello", "payload": {
                "state": engine.state(),
                "recent": bus.recent(60),
            }}))
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20.0)
                    await ws.send_text(json.dumps(event))
                except asyncio.TimeoutError:
                    await ws.send_text(json.dumps({"type": "ping"}))
        except (WebSocketDisconnect, RuntimeError):
            pass
        except Exception as exc:                            # pragma: no cover
            log.debug("ws closed: %s", exc)
        finally:
            bus.unsubscribe(queue)

    @app.get("/api/stream")
    async def sse_stream(request: Request) -> StreamingResponse:
        queue = bus.subscribe()

        async def gen():
            try:
                yield f"data: {json.dumps({'type': 'hello', 'payload': {'state': engine.state(), 'recent': bus.recent(60)}})}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                        yield f"data: {json.dumps(event)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                bus.unsubscribe(queue)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ------------------------------------------------------------------
    # static / index
    # ------------------------------------------------------------------
    @app.get("/")
    async def index():
        path = os.path.join(web_dir, "index.html")
        if os.path.isfile(path):
            return FileResponse(path)
        return JSONResponse({"detail": "web/index.html not found", "web_dir": web_dir}, status_code=404)

    @app.get("/favicon.ico")
    async def favicon():
        path = os.path.join(web_dir, "favicon.svg")
        if os.path.isfile(path):
            return FileResponse(path, media_type="image/svg+xml")
        return JSONResponse({}, status_code=204)

    return app


app = create_app()
