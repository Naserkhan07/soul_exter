"""
SOUL EXTER — an LLM trading floor.

A trading desk where every trade candidate found by the scanner is a trader
sitting at a desk, and every elevated glass cabin is a different open-source
LLM that has to approve or reject the trade. Trades that split the council are
escalated to the CEO (a 6th, larger LLM) who has the final say.

Designed to run on a free Kaggle GPU (2 x T4) — see kaggle/.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
