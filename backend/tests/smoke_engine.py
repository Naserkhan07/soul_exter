"""Headless smoke test: boot the engine, run floor-time, assert the pipeline works."""
import asyncio, sys, time, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from soul_exter.core.engine import FloorEngine
from soul_exter.core.settings import Settings
from soul_exter.core.layout import get_nav

async def main(seconds=45.0, speed=6.0):
    nav = get_nav()
    print(f"nav grid {nav.cols}x{nav.rows} cell={nav.cell}m walkable={sum(nav.walk)}")
    s = Settings()
    s.speed = speed
    s.live_venues = False
    s.ambient_traders = 8
    s.scan_interval = 0.6
    s.scan_batch = 24
    eng = FloorEngine(s)
    t0 = time.time()
    await eng.start()
    seen_states = set()
    off_mesh = []
    while time.time() - t0 < seconds:
        await asyncio.sleep(0.5)
        for tr in eng.trades.values():
            seen_states.add(tr.state)
        for w in eng.walkers.values():
            if not nav.walkable(w.x, w.z):
                off_mesh.append((w.id, round(w.x,2), round(w.z,2), w.kind))
    await eng.stop()
    print("clock:", round(eng.clock,1), "spawned:", eng.stats['spawned'],
          "accepted:", eng.stats['accepted'], "rejected:", eng.stats['rejected'],
          "exited:", eng.stats['exited'])
    print("states seen:", sorted(seen_states))
    print("off-mesh samples:", len(off_mesh), off_mesh[:6])
    for t in list(eng.trades.values())[:4]:
        print(f"  {t.id} {t.symbol} {t.direction} state={t.state} outcome={t.outcome} "
              f"votes={t.votes_for}/{t.votes_against} cabins={len([s for s in t.stages if s.kind=='cabin'])} "
              f"exec={'y' if any(s.kind=='executive' for s in t.stages) else 'n'} pnl={t.pnl_r}")
    print("outcomes:", [(o.trade_id, o.accepted, o.eval_pnl_r) for o in eng.outcomes[:4]])
    print("fly:", eng.brain.last.get('state'), "strikes:", eng.brain.strikes)
    print("funnel:", eng.scanner.funnel)
    print("debate msgs:", len(eng.council.debate_log), "lessons:", len(eng.playbook.lessons))
    return eng

if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv)>1 else 45.0,
                     float(sys.argv[2]) if len(sys.argv)>2 else 6.0))
