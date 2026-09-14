"""Order routing.

The floor places trades through a broker adapter. Two are implemented:

* ``paper``  — simulated fills recorded in memory (default; always available).
* ``mt5``    — MetaTrader 5 via the official ``MetaTrader5`` python package.

MT5 needs the terminal installed *and running on the same machine* (the package
only ships Windows wheels; on Linux it works under Wine). When it is missing or
the credentials do not log in, the adapter reports why and the floor keeps
running in paper mode instead of silently pretending an order went out.
"""
from .mt5 import Broker, MT5Broker, PaperBroker, OrderResult, contract_size, get_broker

__all__ = ["Broker", "MT5Broker", "PaperBroker", "OrderResult", "contract_size", "get_broker"]
