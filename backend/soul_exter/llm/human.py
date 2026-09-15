"""The human layer — how the desks talk like colleagues instead of scripts.

Everything a desk says passes through here on the way out:

* **memory** — each seat remembers the operator's name, what you talked about,
  what it answered, and which phrasing it used last, so it never repeats itself
  and can naturally say "going back to your EURUSD question…",
* **voice** — warm openers, contractions, varied rhythm, a follow-up question
  like a real colleague would ask,
* **general knowledge** — a curated, correct answer bank for everything outside
  the tape (tech, science, money-in-life, classics like "why is the sky blue"),
* **honest reasoning** — when something is genuinely outside what the desk can
  know, it says so like a person would ("I genuinely don't know — here's how I
  would reason about it and what I'd check"), instead of deflecting.

Nothing here is one prepared answer: replies are *composed* from the desk's
lens + the live floor numbers + memory + the question's actual intent.
"""
from __future__ import annotations

import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
#  memory — per-seat conversation state
# --------------------------------------------------------------------------- #
_MEM: Dict[str, Dict[str, Any]] = {}
_STOP_NAMES = {"good", "fine", "ok", "okay", "sure", "back", "here", "done", "sorry",
               "asking", "new", "just", "trying", "looking", "wondering", "curious",
               "not", "so", "very", "really", "great", "well", "glad", "afraid",
               "trading", "working", "ready", "lost", "confused"}


def _mem(seat_id: str) -> Dict[str, Any]:
    if seat_id not in _MEM:
        _MEM[seat_id] = dict(name="", history=[], last_opener="", last_followup=0)
    return _MEM[seat_id]


OPERATOR = {"name": ""}


def remember_name(seat_id: str, question: str) -> str:
    """Capture and remember the operator's name — every desk knows them by it."""
    m = re.search(r"\b(?:my name is|call me|i am called|name'?s)\s+([A-Za-z][a-zA-Z]{1,20})\b",
                  question, re.IGNORECASE)
    if m:
        candidate = m.group(1).strip().title()
        if candidate.lower() not in _STOP_NAMES:
            OPERATOR["name"] = candidate
            return candidate
    return ""


def operator_name(seat_id: str) -> str:
    return OPERATOR.get("name") or ""


def recall(seat_id: str) -> List[dict]:
    return list(_mem(seat_id).get("history") or [])


def remember_exchange(seat_id: str, question: str, topic: str,
                      symbol: str = "") -> None:
    h = _mem(seat_id)
    hist: List[dict] = h.get("history") or []
    hist.append(dict(q=question[:160], topic=topic, symbol=symbol or "", ts=time.time()))
    h["history"] = hist[-12:]


def memory_reference(seat_id: str, topic: str, symbol: str = "") -> str:
    """A natural callback to an earlier exchange, if one fits."""
    hist = recall(seat_id)
    if len(hist) < 2:
        return ""
    for prev in reversed(hist[:-1]):
        if symbol and prev.get("symbol") and prev["symbol"] != symbol:
            continue
        if prev.get("topic") and prev["topic"] not in ("greeting", "smalltalk") \
                and prev["topic"] != topic:
            return (f"Going back to what you asked me earlier about "
                    f"{prev.get('symbol') or prev.get('topic')} — happy to dig into that too.")
    return ""


# --------------------------------------------------------------------------- #
#  voice — warm, varied, never the same opener twice in a row
# --------------------------------------------------------------------------- #
def opener(seat_id: str, name: str, role_word: str, rng: Optional[random.Random] = None
           ) -> str:
    rng = rng or random.Random()
    m = _mem(seat_id)
    who = f" {name}" if name else ""
    bank = [
        "", "",
        f"Good question{who} — ",
        f"Honestly{who}, ",
        f"Right, let me give it to you straight{who} — ",
        f"Ah{who}, ",
        f"Okay{who}, ",
        f"Happy you asked{who} — ",
    ]
    opts = [o for o in bank if o != m.get("last_opener")]
    pick = rng.choice(opts)
    m["last_opener"] = pick
    return pick


FOLLOWUPS: Dict[str, List[str]] = {
    "market": ["Want me to walk you through the levels I'd watch on it?",
               "I can pull the exact tape numbers if you want them.",
               "Should I frame it as a trade with entry and invalidation?"],
    "ticket": ["Want the full blow-by-blow of that ticket's numbers?",
               "I can walk you through what would flip my verdict, if you like."],
    "knowledge": ["Want me to go a level deeper on that?",
                  "I can give you the practical, at-the-desk version too — just say so."],
    "general": ["What's the angle you're coming from — I can tailor the answer.",
                "Tell me a bit more and I'll get specific."],
    "sizing": ["Give me your account size and risk appetite and I'll size it exactly."],
}


def followup(seat_id: str, kind: str, rng: Optional[random.Random] = None) -> str:
    rng = rng or random.Random()
    m = _mem(seat_id)
    bank = FOLLOWUPS.get(kind) or FOLLOWUPS["general"]
    pick = rng.choice(bank)
    if pick == m.get("last_followup"):
        pick = rng.choice(bank)
    m["last_followup"] = pick
    return pick


# --------------------------------------------------------------------------- #
#  small talk — the human moments
# --------------------------------------------------------------------------- #
JOKES = [
    "A trader walks into a bar. Then a lounge, then a yacht — because he sized properly "
    "and let one runner go the distance. Okay, okay — real one: why did the trader break "
    "up with the chart? Too many mixed signals.",
    "Why don't traders ever tell secrets in the pit? Because the walls have ears… and the "
    "tape has ticks. I'm here all week.",
    "My stop-loss and I have a great relationship — it's the only one that's ever honest "
    "with me about when I'm wrong.",
    "There are two hard things in trading: sizing, exits, and off-by-one errors in your "
    "own rules.",
    "The market called. It said: 'I'll let you know.' Classic.",
]

WHO_MADE = ("I run on this floor's built-in analyst engine — a reasoning core the SOUL EXTER "
            "architect put together, wired into the live tape, the book and the council's "
            "memory. No cloud call, no script: I read what's happening on the floor right now "
            "and answer from that. Paste a hosted model key on my desk and I get a full "
            "language model's general knowledge on top — but even keyless I'll always give "
            "you a straight answer.")


def how_are_you(seat: Any, ctx: Dict[str, Any]) -> Tuple[str, List[str], str]:
    s = ctx.get("stats") or {}
    spawned = int(s.get("spawned", 0) or 0)
    pnl = float(s.get("pnl_r", 0.0) or 0.0)
    mood = ("buzzing" if spawned and pnl >= 0 else
            "keeping my head down and my sizes honest" if spawned else
            "fresh and ready — the hunt hasn't really started yet")
    who = operator_name(seat.id)
    name_bit = f", {who}" if who else ""
    body = (f"Honestly? {mood.capitalize()}. The floor has done {spawned} tickets"
            + (f" for {pnl:+.1f}R on the book" if spawned else "")
            + f", and my corner of it — {seat.specialty.lower()} — is exactly where I like "
            f"to be. What about you{name_bit} — what are you looking at today?")
    return body, [], "smalltalk"


def whats_my_name(seat: Any, ctx: Dict[str, Any]) -> Tuple[str, List[str], str]:
    who = OPERATOR.get("name") or ""
    if who:
        return (f"You're {who} — I remember. How have the markets been treating you, "
                f"{who}?"), [], "smalltalk"
    return ("I don't think you've told me yet — say 'my name is …' and it sticks for every "
            "desk on this floor."), [], "smalltalk"


EMPATHY_STEPS = [
    "cut your size in half until the bleed stops — pain shrinks when the risk per ticket does",
    "impose a hard cool-off after two losers in a row; no screen, no clicks, twenty minutes",
    "write the reason for each of those losing trades down — the pattern is usually visible "
    "by the third line",
    "check whether those losses share one bucket or session; losing in clusters is a regime "
    "problem, not a you problem",
]


def empathy(seat: Any, ctx: Dict[str, Any], question: str
            ) -> Tuple[str, List[str], str]:
    rng = random.Random()
    who = OPERATOR.get("name") or ""
    name_bit = f", {who}" if who else ""
    steps = rng.sample(EMPATHY_STEPS, 2)
    body = (f"Hey{name_bit} — that feeling is the job, honestly; every professional you "
            f"admire has sat exactly where you are. Two things that actually help: "
            f"(1) {steps[0]}, and (2) {steps[1]}. "
            f"The drawdown arithmetic is brutal — which is why process, not courage, is what "
            f"turns a rough patch around. What did your last few losing trades have in "
            f"common, if anything?")
    return body, [], "smalltalk"


def frequency_answer(seat: Any, ctx: Dict[str, Any], question: str
                     ) -> Tuple[str, List[str], str]:
    body = ("There's no magic number — the honest answer is: as many as your setups allow, "
            "and none when they don't appear. A disciplined intraday trader usually takes 1–5 "
            "real A+ setups a day; forcing ten trades a day is a fee machine for the broker. "
            "This floor hunts continuously but only strikes when the tape is genuinely "
            "directional — most days that's a handful of tickets, not dozens. Frequency is "
            "an output of opportunity, never a target.")
    return body, [], "sizing"


def thanks(seat: Any, ctx: Dict[str, Any]) -> Tuple[str, List[str], str]:
    who = operator_name(seat.id)
    return (f"Anytime{', ' + who if who else ''} — that's what the desk is for. "
            f"Shout if you want me on a ticket or a tape."), [], "smalltalk"


def bye(seat: Any, ctx: Dict[str, Any]) -> Tuple[str, List[str], str]:
    who = operator_name(seat.id)
    return (f"See you around{', ' + who if who else ''} — I'll keep one eye on the tape "
            f"while you're gone."), [], "smalltalk"


def joke(seat: Any, ctx: Dict[str, Any]) -> Tuple[str, List[str], str]:
    rng = random.Random()
    return rng.choice(JOKES), [], "smalltalk"


def sorry(seat: Any, ctx: Dict[str, Any]) -> Tuple[str, List[str], str]:
    return ("Nothing to apologise for — ask me anything, as many times as you like. "
            "That's literally my job."), [], "smalltalk"


def who_made_you(seat: Any, ctx: Dict[str, Any]) -> Tuple[str, List[str], str]:
    return WHO_MADE, [], "smalltalk"


def compliment(seat: Any, ctx: Dict[str, Any]) -> Tuple[str, List[str], str]:
    return ("That's kind of you — but save the flattery for the tape, it's the only thing "
            "that needs convincing. Anything you want me to dig into?"), [], "smalltalk"


# --------------------------------------------------------------------------- #
#  general knowledge — correct, concise, human
# --------------------------------------------------------------------------- #
GLOSSARY: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("api", "application programming interface"), "API",
     "An API (Application Programming Interface) is a contract that lets two programs talk: "
     "you send a structured request, you get a structured response. When this floor pulls a "
     "price or routes an order, it's an API call — same idea as a waiter taking your order "
     "to the kitchen."),
    (("http", "https", "hypertext transfer"), "HTTP",
     "HTTP is the protocol browsers and servers use to exchange text over the web — a request "
     "('GET me this page') and a response ('here it is, status 200'). The S in HTTPS means "
     "it's encrypted end-to-end, so nobody in the middle can read it."),
    (("json", "javascript object notation"), "JSON",
     "JSON is a way of writing data as plain text with braces and quotes — {\"symbol\": "
     "\"EURUSD\", \"price\": 1.08}. Every desk on this floor speaks JSON to its models and to "
     "the broker; humans read it, machines parse it."),
    (("python",), "Python",
     "Python is a programming language optimised for humans-first readability — you write "
     "almost-English and it runs. This entire floor's backend is Python (the council, the fly "
     "brain, the broker bridge), because finance + Python share the best tooling in the world."),
    (("javascript", "typescript"), "JavaScript / TypeScript",
     "JavaScript is the language browsers run — every animation on the 3D floor you're looking "
     "at is JavaScript driving your GPU. TypeScript is JavaScript with types added, which "
     "catches mistakes before runtime; the floor's frontend is written in TypeScript."),
    (("database", "sql"), "Database",
     "A database is organised memory for programs: rows and tables (SQL) or documents "
     "(NoSQL) that you can query fast. Trading systems live and die by theirs — fills, "
     "orders, lessons learned all land in one."),
    (("blockchain",), "Blockchain",
     "A blockchain is an append-only ledger copied across many computers, so no single one "
     "can quietly rewrite history. Blocks are cryptographically chained — that's the whole "
     "trick. Useful where nobody trusts a central bookkeeper; expensive where one does exist."),
    (("artificial intelligence", " what is ai", "what is a.i"), "AI",
     "AI is the umbrella term for software that performs tasks we associate with thinking — "
     "recognising, predicting, planning, conversing. Modern AI is mostly pattern-learning: "
     "show a model enough examples and it generalises. The desks here are language models; "
     "the fly brain is a tiny spiking neural net — both are AI under that umbrella."),
    (("machine learning", " what is ml", "machine-learning"), "Machine learning",
     "Machine learning is statistics that writes its own rules: instead of hand-coding "
     "'if RSI < 30 buy', you show the model thousands of labelled examples and it finds the "
     "weights. The floor's expectancy model is exactly that — fitted on settled tickets, "
     "never on stories."),
    (("neural network", "neural net", "neurons work"), "Neural network",
     "A neural network is a stack of simple units: each takes numbers in, multiplies by "
     "learned weights, adds them, fires if the sum is strong enough. Stack enough layers and "
     "it can approximate almost anything — that's where the fly brain's 26→140→8 architecture "
     "gets its decisions, and where big language models get their words."),
    (("llm", "large language model", "language model", "gpt"), "LLM",
     "An LLM (large language model) is a neural network trained on enormous amounts of text "
     "to predict the next word — and that turns out to teach it grammar, facts, reasoning "
     "patterns and style. The five cabin judges and NAVEED run on open-source LLMs; with a "
     "free API key they think in their own weights, keyless they borrow mine."),
    (("cloud", "cloud computing"), "Cloud computing",
     "Cloud computing is renting someone else's computers by the hour instead of owning "
     "servers — you get an API and a bill. This floor is built to run its heavy parts on a "
     "free cloud GPU (Kaggle) so you pay nothing for compute."),
    (("encryption", "encrypted", "cryptography"), "Encryption",
     "Encryption scrambles information so only someone with the right key can read it. Good "
     "modern encryption (like TLS on this page, or your broker login) is effectively "
     "unbreakable by brute force — the weak points are always passwords and people, not math."),
    (("why is the sky blue", "sky blue"), "Why the sky is blue",
     "Sunlight contains all colours; air molecules scatter short blue wavelengths far more "
     "than long red ones (Rayleigh scattering — roughly 1/λ⁴). So everywhere you look, "
     "scattered blue light arrives from every direction — the sky itself is that scatter. "
     "Sunsets go red because the light takes a longer path and the blue gets scattered away "
     "before it reaches you."),
    (("gravity",), "Gravity",
     "Gravity is the attraction between anything with mass or energy — the more mass, the "
     "stronger the pull, falling off with the square of distance. Newton described the force; "
     "Einstein explained it as mass bending spacetime itself, and objects simply following "
     "the straightest path through the bend."),
    (("electricity",), "Electricity",
     "Electricity is the flow of charge — usually electrons drifting through a conductor — "
     "driven by voltage (pressure) through resistance (friction). Power = voltage × current. "
     "The outlet, the GPU running this floor and the neurons in your head (yes, tiny "
     "electrochemical spikes) are all variations on moving charge."),
    (("photosynthesis",), "Photosynthesis",
     "Photosynthesis is how plants eat light: chlorophyll captures sunlight and uses that "
     "energy to turn water and CO₂ into sugar, releasing oxygen as waste. Almost every "
     "calorie in your food, and every breath of oxygen, traces back to it."),
    (("dna", "genes", "genetics"), "DNA",
     "DNA is the instruction manual for building you — a double helix of four letters "
     "(A, T, G, C) read three at a time as words called genes. Fun fact relevant to this "
     "floor: a fruit fly's brain connectome — the thing animating the FLY BRAIN tab — was "
     "mapped neuron by neuron, about 140,000 of them."),
    (("black hole",), "Black holes",
     "A black hole is mass packed densely enough that escaping it would require moving "
     "faster than light — so nothing gets out, not even light. The edge of no return is the "
     "'event horizon'; outside it, orbits are normal. We've photographed the shadow of two "
     "of them — the physics holds."),
    (("evolution",), "Evolution",
     "Evolution is variation + inheritance + selection, repeated for billions of years: "
     "offspring differ, differences are inherited, and whatever reproduces better becomes "
     "common. It's the same feedback loop this floor borrows — the fly brain's dopamine is "
     "literally an evolutionary-style reward signal training its own choices."),
    (("atom",), "Atoms",
     "Atoms are the smallest unit of an element: a nucleus of protons and neutrons with "
     "electrons arranged around it. 118 kinds are known, everything you've ever touched is "
     "a LEGO build from them, and the behaviour of the electrons explains chemistry, "
     "electricity and why this screen lights up."),
    (("vaccine", "vaccination"), "Vaccines",
     "A vaccine shows your immune system a harmless preview of a pathogen — a protein, a "
     "weakened or killed version, or just the instructions (mRNA) — so it builds memory "
     "cells in advance. When the real thing shows up, the response starts immediately "
     "instead of from scratch. That's the whole idea; the rest is biology's paperwork."),
    (("antibiotic", "antibiotics"), "Antibiotics",
     "Antibiotics are drugs that kill bacteria — by breaking their cell walls, or their "
     "protein factories — without touching your own cells. They do nothing against viruses "
     "(different machinery), which is why doctors won't prescribe them for a cold. Overuse "
     "breeds resistance, which is the scary part."),
    (("compound interest",), "Compound interest",
     "Compound interest is interest earning interest: at 10% a year, money doubles roughly "
     "every 7.2 years (the rule of 72 — divide 72 by the rate). The same math runs in "
     "reverse on leverage and credit-card debt, which is why the floor treats borrowing "
     "cost as a per-trade number, not an afterthought."),
    (("inflation", "what is inflation"), "Inflation",
     "Inflation is money losing purchasing power over time — prices drift up, so the same "
     "note buys less. It's driven by demand outrunning supply, or by the money supply "
     "growing. Central banks fight it with higher rates, which is exactly why inflation "
     "prints move every market this floor tracks."),
    (("credit score",), "Credit scores",
     "A credit score is a number summarising how reliably you repay borrowed money — built "
     "from payment history, amounts owed, length of history, new credit and mix. Lenders "
     "price your rate off it. Treat it like a trading track record: small consistent "
     "positives compound, one blow-up haunts for years."),
    (("mortgage",), "Mortgages",
     "A mortgage is a loan secured by the property itself — the house is the collateral, so "
     "rates are lower than unsecured debt. Early payments are mostly interest; refinancing "
     "is repricing the loan against your current situation. It's leverage on an asset, "
     "which is why this floor's rule — survive the drawdown first — applies to houses too."),
    (("time zone", "timezones", "time zones"), "Time zones",
     "Time zones are 24-ish longitudinal slices of the world, each nominally one hour apart "
     "from UTC. Markets live and die by them: Tokyo opens 00:00 UTC, London 08:00, New York "
     "13:30 (during summer), and the liquidity of this floor follows that exact rhythm."),
    (("internet", "how does the internet work"), "The internet",
     "The internet is a network of networks that agree on how to address each other (IP) "
     "and transport data reliably (TCP). Your request hops router to router — often through "
     "fibre under an ocean — in about 30–200 ms. This floor's websocket frames make the "
     "same trip dozens of times a second."),
    (("quantum", "quantum computing"), "Quantum computing",
     "Quantum computers use qubits, which can hold superpositions of 0 and 1 and can be "
     "entangled, letting certain problems (factoring, simulating molecules, some "
     "optimisation) collapse from years to hours. They don't make everything faster — for "
     "ordinary computing, your laptop is still king."),
    (("sun", "solar system"), "The Sun",
     "The Sun is a middle-aged star fusing about 600 million tonnes of hydrogen every "
     "second, holding 99.86% of the solar system's mass. Its light takes 8 minutes 20 "
     "seconds to reach you — which means every sunny day is a view 8 minutes into the past."),
    (("moon",), "The Moon",
     "The Moon is Earth's only natural satellite, about 384,000 km away, tidally locked so "
     "one face always points at us. Its gravity drives our tides and steadies Earth's axial "
     "wobble — no Moon, and our climate would wander like a drunk sailor's."),
    (("ocean", "pacific"), "The ocean",
     "The Pacific is the big one — covering roughly a third of Earth's surface, with the "
     "Mariana Trench deeper than Everest is tall. The oceans drive weather, absorb about a "
     "quarter of our CO₂, and carry most of the world's trade on ships — including the "
     "commodity flows every futures contract here references."),
    (("everest", "highest mountain"), "Mount Everest",
     "Everest is Earth's highest peak above sea level — 8,849 m — on the Nepal–China border. "
     "It's still growing a few millimetres a year as India keeps driving into Asia. Fun "
     "nuance: due to Earth's equatorial bulge, Chimborazo in Ecuador sits farther from "
     "Earth's centre."),
    (("currency", "money work", "fiat"), "How money works",
     "Modern money is fiat: valuable because governments demand taxes in it and everyone "
     "else follows. Central banks manage its supply; exchange rates are just the price of "
     "one country's promises versus another's. Every FX pair on this floor is exactly that "
     "comparison, ticking in real time."),
    (("stock market work", "how do stocks work", "shares"), "How stocks work",
     "A share is a slice of ownership in a company — you own part of the factories, brands "
     "and future profits. Prices move on two beats: what the company earns (fundamentals) "
     "and what the crowd feels (flows and sentiment). Exchanges are the auction halls where "
     "both meet every second."),
    (("etf", "exchange traded fund"), "ETFs",
     "An ETF is a basket of assets that trades like a single stock — one click gives you a "
     "slice of, say, 500 companies. Most are passive (tracking an index) with tiny fees, "
     "which is why they've eaten the mutual-fund world. Liquidity is the catch: check the "
     "spread before assuming the price is fair."),
    (("short selling", "shorting", "short a stock"), "Short selling",
     "Shorting is betting on a fall: borrow the asset, sell it, hope to buy it back cheaper "
     "and pocket the difference. Risk is asymmetric — losses are unbounded above — which is "
     "why every short ticket on this floor carries the same hard 1×ATR stop as the longs. "
     "Short the idea, never the hope."),
    (("leverage work", "how does leverage work"), "How leverage works",
     "Leverage is borrowing to size up: 10× leverage means a 1% move in the asset is 10% on "
     "your capital — in either direction. It doesn't change your edge, only the violence of "
     "the ride. This floor prefers honest size with hard stops over leverage heroics; "
     "survival compounds, blow-ups don't."),
)


def glossary_answer(question: str) -> Optional[Tuple[str, List[str], str]]:
    """Look up a general-knowledge question ('what is X', 'explain X', 'how does X work').

    Keys match as WHOLE WORDS only — 'capital' must never trip the 'API' entry."""
    q = question.lower().strip().rstrip("?").strip()
    if not any(k in q for k in ("what is", "what's", "explain", "how does", "how do",
                                "tell me about", "define", "meaning of", "why is",
                                "why are", "what are")):
        return None
    for keys, title, body in GLOSSARY:
        for k in keys:
            if re.search(rf"(?<![a-z0-9]){re.escape(k)}(?:s|es)?(?![a-z0-9])", q):
                return body, [title], "knowledge"
    return None


# --------------------------------------------------------------------------- #
#  honest fallback — a real attempt, not a deflection
# --------------------------------------------------------------------------- #
def human_fallback(seat: Any, ctx: Dict[str, Any], question: str,
                   rng: Optional[random.Random] = None) -> Tuple[str, List[str], str]:
    """Say something genuinely useful about an out-of-lane question, like a person would."""
    rng = rng or random.Random()
    who = operator_name(seat.id)
    q = question.strip().rstrip("?")
    short = q if len(q) <= 60 else q[:57] + "…"
    known_gloss = glossary_answer(question)
    if known_gloss:
        body, ev, kind = known_gloss
        return body, ev, kind
    frame = (
        f"Straight answer{', ' + who if who else ''}: that one's outside what I can see from "
        f"this desk — my world is this floor: the tape, the tickets, the book, risk and "
        f"execution, plus the general stuff a trader reads about. I won't invent facts to "
        f"sound smart; that's a habit the market beats out of you fast. ")
    angle = rng.choice([
        "Here's how I'd think it through anyway: define what a good answer would need to be "
        "true, split it into what's checkable and what's opinion, then check the checkable "
        "parts first. ",
        "The trader's version of an answer: what would have to be true for 'yes', what "
        "would make it 'no', and what evidence would separate them. Apply that frame and "
        "most questions half-answer themselves. ",
        "My instinct is to size the question first: what decision does the answer change? "
        "If nothing changes, it's curiosity — fun, but cheap. If something changes, we go "
        "find real data before spending a unit of risk on it. ",
    ])
    offer = rng.choice([
        "Give me the context behind it and I'll reason it through with you properly.",
        "Try me again with a bit more detail and I'll get you somewhere useful.",
        "Or ask me about a market, a ticket, sizing — there I'm on home ground and "
        "you'll get exact numbers, not philosophy.",
    ])
    return frame + angle + offer, [], "general"
