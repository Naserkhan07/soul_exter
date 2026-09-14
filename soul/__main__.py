"""`python -m soul` -> open the floor.

    python -m soul                 # auto: real models on GPU, mock on CPU
    SOUL_MOCK_LLM=1 python -m soul # force synthetic cabins (no GPU needed)
    SOUL_PORT=8000 python -m soul
"""
from __future__ import annotations

import logging
import os
import sys

import uvicorn

from .api import create_app
from .config import load_config


def main() -> int:
    cfg = load_config()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)-16s %(message)s",
        datefmt="%H:%M:%S",
    )
    app = create_app(cfg)
    print(f"\n  SOUL EXTER — LLM trading floor")
    print(f"  http://{cfg.host}:{cfg.port}")
    print(f"  mock_llm={cfg.mock_llm} profile={cfg.model_profile} venue={cfg.venue}\n")
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level=cfg.log_level,
                ws_ping_interval=20, ws_ping_timeout=20)
    return 0


if __name__ == "__main__":
    sys.exit(main())
