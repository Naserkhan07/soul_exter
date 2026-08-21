"""
The agent loop — the heart of the project.

    START
      -> planner picks (location, category)
      -> discovery tools return candidates (web search / HF dataset / Reddit)
      -> deduplicate against everything already seen
      -> executor investigates each candidate
      -> Qwen qualifies + scores
      -> qualified leads saved to SQLite (Excel is exported on demand)
      -> checkpoint
      -> next cell
    ... then STOP. No contacting, ever.

Discovery sources (all optional & replaceable — no paid dependency):
    * web search (Brave/SerpAPI free tier) over the geography x category grid
    * Hugging Face company dataset (streamed, India-filtered)
    * Reddit explicit-intent signals (official API, read-only)
    * manual seed lists (python main.py seed file.json)
"""

import logging
import re
import signal
from urllib.parse import urlparse

import config
from agent.checkpoint import load_checkpoint, save_checkpoint
from agent.executor import Executor
from agent.memory import Memory
from agent.planner import Planner
from database.database import LeadDatabase
from database.deduplication import identity_key, merge_leads
from tools import reddit, web_search, huggingface as hf

log = logging.getLogger("agent.loop")

# aggregators/directories/socials/travel-listicle sites — search results from
# these are not a business's own website, so they can't be investigated as one
_NON_BUSINESS_HOSTS = (
    "justdial", "indiamart", "sulekha", "tradeindia", "yelp", "zomato",
    "swiggy", "tripadvisor", "facebook", "instagram", "linkedin", "youtube",
    "twitter", "x.com", "wikipedia", "quora", "reddit", "amazon", "flipkart",
    "olx", "magicbricks", "99acres", "glassdoor", "indeed", "naukri",
    "google.", "yellowpages", "yahoo",
    # travel/food listicle & directory sites seen in real runs
    "wanderlog", "holidify", "tripzygo", "makemytrip", "evendo", "ellopages",
    "wanderon", "magicpin", "dineout", "eazydiner", "yatra", "goibibo",
    "cleartrip", "thrillophilia", "traveltriangle", "curlytales", "lbb.in",
    "whatshot", "slurrp", "restaurantguru", "threebestrated", "grotal",
    "asklaila", "mouthshut", "medium.com", "blogspot", "wordpress.com",
    "pinterest", "timesofindia", "hindustantimes", "ndtv", "news18",
    "top10", "bestof", "vymaps", "placedigger", "veyor",
)

# reject listicle/guide TITLES like "15 Best Restaurants in ...",
# "Top 12 Places to Eat", "... (2026 ranked)" — those are articles,
# not businesses
_LISTICLE_TITLE = re.compile(
    r"^\s*\d+\s|\b(top\s*\d*|best|list of|places? to|guide|ranked|"
    r"near me|reviews? of|cheapest|famous|must[- ]visit|things to)\b", re.I)


class AgentLoop:
    def __init__(self, priority_states=None, categories=None,
                 use_web_search=True, use_hf=True, use_reddit=True):
        self.state = load_checkpoint()
        self.planner = Planner(self.state, priority_states, categories)
        self.executor = Executor()
        self.db = LeadDatabase()
        self.memory = Memory()
        self.use_web_search = use_web_search
        self.use_hf = use_hf
        self.use_reddit = use_reddit
        self._stop = False
        signal.signal(signal.SIGINT, self._graceful_stop)

    def _graceful_stop(self, *_):
        log.info("Stop requested — finishing current candidate then saving")
        self._stop = True

    # ------------------------------------------------------------------ #
    def run(self, max_candidates: int | None = None,
            extra_candidates: list | None = None) -> dict:
        """
        Run until the grid is exhausted, max_candidates processed, or Ctrl+C.
        `extra_candidates` lets you inject manual/seed candidates.
        """
        processed = 0
        budget = max_candidates or float("inf")

        # 0) Reddit intent signals once per session (highest intent first)
        pipeline = list(extra_candidates or [])
        if self.use_reddit:
            pipeline += self._reddit_candidates()

        while not self._stop and processed < budget:
            if not pipeline:
                pipeline = self._discover_batch()
                if not pipeline:
                    log.info("No more candidates from any source — stopping")
                    break

            candidate = pipeline.pop(0)
            processed += 1
            self.state["total_candidates_processed"] = (
                self.state.get("total_candidates_processed", 0) + 1)

            key = identity_key(
                name=candidate.get("business_name", ""),
                website=candidate.get("website", ""),
                phone=candidate.get("phone", ""),
                city=(candidate.get("location_meta") or {}).get("city", ""),
                linkedin=candidate.get("linkedin", ""),
            )
            if self.db.has_seen(key):
                self.memory.record("duplicate_skipped",
                                   candidate.get("business_name", ""))
                continue
            self.db.mark_seen(key)

            try:
                lead, qualification = self.executor.investigate(candidate)
            except Exception as exc:
                log.exception("Investigation failed for %s: %s",
                              candidate.get("business_name"), exc)
                self.memory.record("investigation_error")
                continue

            if lead is None:
                self.memory.record("not_qualified",
                                   candidate.get("business_name", ""))
            else:
                existing = self.db.get_lead(lead.lead_id)
                if existing:
                    lead = merge_leads(existing, lead)
                self.db.upsert_lead(lead)
                self.state["total_leads_saved"] = (
                    self.state.get("total_leads_saved", 0) + 1)
                self.memory.record("lead_saved", lead.business_name)

            if processed % config.BATCH_SIZE == 0:
                save_checkpoint(self.state)
                log.info("Batch checkpoint. Progress: %s | Memory: %s",
                         self.planner.progress(), self.memory.summary())

        save_checkpoint(self.state)
        summary = {
            "processed_this_session": processed,
            "db": self.db.stats(),
            "planner": self.planner.progress(),
            "memory": self.memory.summary(),
        }
        log.info("Session done: %s", summary)
        return summary

    # ------------------------------------------------------------------ #
    def _discover_batch(self) -> list:
        """Pull the next batch of candidates from whichever sources work."""
        candidates = []

        # 1) geography-grid discovery via keyless/free web search.
        #    Try a few grid cells — one empty result must not stall the agent.
        if self.use_web_search:
            for _ in range(5):
                target = self.planner.current_target()
                if not target or candidates:
                    break
                loc = target["location"]
                candidates += self._web_search_candidates(
                    target["category"], loc)
                self.memory.record(
                    "web_search_query",
                    f"{target['category']} @ {loc['query_location']}")
                self.planner.advance()
        elif self.planner.current_target():
            # search disabled: still advance so HF stays the primary source
            self.planner.advance()

        # 2) HF company dataset (streamed, resumable via checkpoint offset)
        if self.use_hf and len(candidates) < config.BATCH_SIZE:
            offset = self.state.get("hf_dataset_offset", 0)
            hf_batch = list(hf.iter_india_companies(
                limit=config.BATCH_SIZE, skip=offset))
            if hf_batch:
                self.state["hf_dataset_offset"] = max(
                    c.get("_dataset_offset", offset) for c in hf_batch)
                candidates += hf_batch
                self.memory.record("hf_batch", f"offset={offset}")

        return candidates

    # ------------------------------------------------------------------ #
    def _web_search_candidates(self, category: str, loc: dict) -> list:
        """Turn search results for 'category in location' into candidates."""
        query = f"{category} in {loc['query_location']}"
        results = web_search.search_web(
            query, max_results=config.MAX_CANDIDATES_PER_QUERY)
        out, seen_hosts = [], set()
        for r in results:
            url = r.get("url", "")
            host = urlparse(url).netloc.lower()
            if not url or host in seen_hosts:
                continue
            if any(bad in host for bad in _NON_BUSINESS_HOSTS):
                continue
            title = r.get("title", "")
            if _LISTICLE_TITLE.search(title):
                continue  # article/guide, not a business site
            seen_hosts.add(host)
            # take the part of the title before "|", "-", "–" as the name
            name = re.split(r"\s+[|\-–:]\s+", title)[0].strip() or host
            out.append({
                "source": "web_search",
                "business_name": name[:100],
                "business_category": category,
                "website": f"{urlparse(url).scheme}://{host}",
                "address": loc["query_location"],
                "location_meta": loc,
                "source_url": url,
            })
        log.info("Web search: %d business candidates for '%s'",
                 len(out), query)
        return out

    def _reddit_candidates(self) -> list:
        signals = reddit.search_reddit()
        out = []
        for s in signals:
            out.append({
                "source": "reddit",
                "business_name": s["title"][:80],
                "business_category": "unknown (reddit signal)",
                "website": "",
                "explicit_demand": s["explicit_demand"],
                "source_url": s["url"],
                "reddit_needs": s["detected_needs"],
            })
        if out:
            self.memory.record("reddit_signals", str(len(out)))
        return out
