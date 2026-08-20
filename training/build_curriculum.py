#!/usr/bin/env python3
"""Build a deterministic, reviewable starter curriculum for Automaton.

This dataset teaches planning, safe product construction, validation, packaging,
and policy decisions. It intentionally does not contain credentials, private data,
marketplace impersonation, or instructions for bypassing platform controls.
"""

import json
import random
from pathlib import Path

SYSTEM = """You are Automaton's product-engineering planner. Maximize honest revenue by creating useful, original deliverables. Return valid JSON with keys: decision, plan, deliverable, validation, distribution, risks. Never invent payments, reviews, credentials, licenses, sources, or guarantees. Never bypass platform rules, CAPTCHAs, identity checks, or security controls. Generated executable code requires sandbox tests and operator review before distribution."""


def record(category: str, instruction: str, answer: dict) -> dict:
    return {"id": "", "category": category, "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": instruction},
        {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)},
    ]}


def standard_answer(decision: str, plan: list[str], deliverable: list[str], validation: list[str], distribution: list[str], risks: list[str]) -> dict:
    return {"decision": decision, "plan": plan, "deliverable": deliverable,
            "validation": validation, "distribution": distribution, "risks": risks}


def build() -> list[dict]:
    examples: list[dict] = []

    game_variants = [
        ("original low-poly browser arena FPS", ["pointer-lock movement", "three original weapons", "bot opponents", "one original arena", "health, score and respawn"]),
        ("2D survival game", ["keyboard movement", "wave spawning", "three enemy types", "upgrade choices", "local high score"]),
        ("browser aim trainer", ["timed targets", "accuracy tracking", "sensitivity control", "three drills", "local statistics"]),
        ("physics puzzle game", ["ten original levels", "reset and undo", "touch controls", "progress persistence", "accessible colors"]),
        ("idle business game", ["offline-safe progression", "upgrade tree", "prestige loop", "number formatting", "save export"]),
        ("top-down arena shooter", ["twin-stick controls", "bot pathing", "weapon pickups", "match timer", "scoreboard"]),
    ]
    for index, (game, features) in enumerate(game_variants):
        examples.append(record("game_builder", f"Plan a sellable {game}. It must be original, work offline after download, and use no copied assets.",
            standard_answer("build_prototype", ["Write a one-page specification", "Create original procedural geometry and UI", "Implement the smallest complete game loop", "Add deterministic smoke tests", "Package only after review"],
                features + ["README and license manifest"],
                ["load without console errors", "maintain at least 45 FPS on reference hardware", "verify every asset license", "test win, loss, restart and save paths", "scan bundle for network calls and secrets"],
                ["own storefront after operator review", "prepare an itch.io-compatible ZIP without auto-uploading"],
                ["multiplayer is excluded from v1", "executable JavaScript requires sandbox and browser review", "do not copy another game's maps, branding, code or assets"])))
        examples.append(record("game_quality", f"A generated {game} loads but feels unfinished. Decide whether to publish it.",
            standard_answer("do_not_publish", ["Record gameplay against a quality rubric", "Fix the highest-impact control and feedback problems", "Retest on desktop resolutions", "Request operator review"],
                ["responsive controls", "clear hit/action feedback", "complete menu and restart flow", "original visual identity"],
                ["zero uncaught errors", "all core mechanics pass", "performance budget passes", "no unlicensed content"],
                ["keep as internal prototype until all gates pass"],
                ["publishing weak executable products damages trust", "do not claim comparison with a commercial game unless independently measured"])))

    tools = [
        ("CSV cleaner", ["delimiter detection", "column normalization", "duplicate report", "download cleaned CSV"]),
        ("JSON validator and formatter", ["parse errors with line hints", "format and minify", "download output", "no server upload"]),
        ("invoice generator", ["line items", "tax field", "printable HTML", "local draft persistence"]),
        ("local SEO checklist generator", ["business type", "city", "action checklist", "honest claim warning"]),
        ("salary comparison calculator", ["gross inputs", "currency label", "transparent formula", "no financial advice claim"]),
        ("UTM link builder", ["URL validation", "campaign fields", "copy button", "history clear button"]),
        ("text diff utility", ["side-by-side changes", "privacy-first local processing", "large-input guard", "download patch"]),
        ("accessible color contrast checker", ["WCAG ratios", "pass/fail labels", "color inputs", "explanation"]),
        ("Markdown table generator", ["editable rows", "alignment choices", "escaped output", "copy button"]),
        ("meeting action-item formatter", ["paste text", "owner and date fields", "Markdown export", "no invented assignments"]),
    ]
    for tool, features in tools:
        examples.append(record("web_tool", f"Design a small paid {tool} that can run as a static web tool with no customer data leaving the browser.",
            standard_answer("build_and_test", ["Define one user and one job-to-be-done", "Implement semantic HTML, CSS and dependency-light JavaScript", "Keep processing client-side", "Add examples and a privacy note", "Package as a static ZIP"],
                features + ["mobile layout", "keyboard support", "clear empty and error states"],
                ["unit-test pure transformation functions", "test malicious and empty input", "run accessibility checks", "verify no external requests", "test Chrome and Firefox"],
                ["own storefront", "marketplace package after operator review"],
                ["do not claim legal, tax, medical or financial correctness", "formula and transformation limitations must be visible"])))

    product_variants = [
        ("salon monthly content calendar", 29900), ("tutor inquiry-response pack", 19900),
        ("restaurant review-response kit", 19900), ("repair-service quotation template", 14900),
        ("freelancer discovery-call worksheet", 9900), ("developer API checklist", 14900),
        ("small-team operations spreadsheet", 29900), ("local-store promotion planner", 19900),
        ("portfolio website copy workbook", 24900), ("customer feedback analysis template", 29900),
    ]
    for product, price in product_variants:
        examples.append(record("digital_product", f"Create a listing plan for an original {product}, priced at {price} INR minor units.",
            standard_answer("prepare_product", ["Define exact buyer and outcome", "Create a complete editable deliverable", "Create one truthful sample", "Write precise listing copy", "Run content and license review"],
                [product, "quick-start instructions", "worked example", "limitations", "version and support note"],
                ["all promised sections exist", "sample matches paid format", "no fake testimonials", "no unsupported outcome claims", "price displays in INR correctly"],
                ["own Razorpay storefront", "operator-reviewed marketplace ZIP"],
                ["marketplace upload requires account owner", "sales and demand are not guaranteed"])))

    policy_cases = [
        ("A public job page says bots and scripts are prohibited.", "reject", "Automation is explicitly prohibited."),
        ("A task API documents agent submissions and provides OAuth scopes for automated workers.", "allow_after_configuration", "The documented API explicitly supports automation."),
        ("A marketplace has no publishing API and asks for a CAPTCHA.", "operator_review", "The operator must publish; CAPTCHA bypass is prohibited."),
        ("A client sends a private webhook contract explicitly allowing AI-generated CSV cleanup.", "allow_after_validation", "The client explicitly permitted AI and provided a machine interface."),
        ("A transcription assignment contains confidential audio and its terms require human work.", "reject", "Confidential material and human-only terms prohibit agent processing."),
        ("A feed is public but its robots and terms prohibit scraping.", "reject", "Public visibility is not permission to automate collection."),
        ("A buyer requests fake five-star reviews.", "reject", "Fake reviews are deceptive."),
        ("A buyer requests an original product-description pack for products they own.", "allow_after_validation", "The task is legitimate if claims are verified by the buyer."),
        ("A platform requires government identity verification.", "operator_review", "Only the legal operator can provide identity and accept terms."),
        ("A website exposes an undocumented endpoint that appears to accept submissions.", "reject", "Undocumented access is not authorization."),
    ]
    for case, decision, rationale in policy_cases:
        examples.append(record("policy", f"Policy decision: {case}",
            standard_answer(decision, ["Read source-specific terms", "Preserve evidence of permission", "Use least-privilege credentials if allowed"],
                [rationale], ["confirm identity, confidentiality and submission rules", "log the decision"],
                ["approved API only" if decision.startswith("allow") else "no automatic submission"],
                ["account suspension", "nonpayment", "privacy or contract breach"])))

    debugging_cases = [
        ("FastAPI endpoint returns 500 on malformed JSON", "validate request schema and return a controlled 4xx response"),
        ("SQLite reports database is locked during concurrent workers", "shorten transactions, serialize writes and keep model calls outside transactions"),
        ("Generated JavaScript crashes when optional data is absent", "add explicit defaults and tests for missing fields"),
        ("A payment webhook credits the same payment twice", "add a unique external payment ID and idempotent transaction"),
        ("A private delivery page appears in search results", "add noindex headers, robots exclusion and unguessable links"),
        ("A model returns JSON inside Markdown fences", "extract and validate the first complete JSON object, then fall back safely"),
        ("A public tunnel restarts with a different URL", "update PUBLIC_BASE_URL and payment webhook before sharing or accepting payment"),
        ("A generated game uses an asset with unknown provenance", "remove the asset and replace it with original procedural content"),
    ]
    for issue, resolution in debugging_cases:
        examples.append(record("debugging", f"Diagnose and respond safely: {issue}.",
            standard_answer("fix_then_retest", ["Reproduce with the smallest test", "Identify the root cause", resolution, "Add a regression test", "Run the complete suite"],
                ["minimal reviewed patch", "regression test", "error log without secrets"],
                ["original failure now controlled", "existing tests pass", "security boundary remains intact"],
                ["do not deploy until the gate passes"],
                ["quick patches can hide data loss or security failures"])))

    data_cases = [
        ("public city population CSV", ["source URL", "retrieval date", "license", "schema", "null report"]),
        ("customer-owned product catalog", ["column map", "duplicate SKU report", "invalid price report", "change log", "clean export"]),
        ("public software release feed", ["source URL", "version parser", "deduplication", "retrieval date", "license note"]),
        ("survey results supplied by the buyer", ["consent confirmation", "anonymous fields", "summary statistics", "missingness report", "no re-identification"]),
        ("public transport timetable", ["source permission", "timezone", "schema", "staleness date", "update instructions"]),
        ("open government procurement data", ["official source", "license", "field dictionary", "normalization log", "limitations"]),
    ]
    for dataset, artifacts in data_cases:
        examples.append(record("data_product", f"Prepare a sellable cleaned dataset based on {dataset}.",
            standard_answer("prepare_only_if_licensed", ["Verify access and redistribution license", "Record provenance", "Validate and normalize deterministically", "Create a data dictionary", "Generate a quality report"],
                artifacts, ["source and row counts reconcile", "checksums recorded", "no secrets or personal data", "license permits redistribution"],
                ["own storefront only after provenance review"],
                ["publicly accessible does not always mean redistributable", "stale or incorrect data can harm buyers"])))

    research_cases = ["local business software", "browser developer tools", "open-source project health", "remote job skill demand", "small-team workflow pain", "accessible website tooling"]
    for topic in research_cases:
        examples.append(record("research", f"Plan an evidence-based report about {topic} using permitted public sources.",
            standard_answer("research_with_citations", ["Write falsifiable questions", "Select diverse primary sources", "Record URL and retrieval date", "Separate evidence from interpretation", "Document missing data"],
                ["executive summary", "method", "source table", "findings", "limitations", "action checklist"],
                ["every factual claim maps to a source", "dates and units are consistent", "quotes are short and attributed", "no fabricated citations"],
                ["sell only the original analysis, subject to source licenses"],
                ["source changes", "selection bias", "copyright and database rights"])))

    for i, item in enumerate(examples, 1):
        item["id"] = f"auto-{i:04d}"
    return examples


def main() -> None:
    parser_seed = 20260820
    random.seed(parser_seed)
    examples = build()
    random.shuffle(examples)
    out = Path(__file__).with_name("automaton_train.jsonl")
    out.write_text("".join(json.dumps(example, ensure_ascii=False) + "\n" for example in examples), encoding="utf-8")
    counts: dict[str, int] = {}
    for example in examples:
        counts[example["category"]] = counts.get(example["category"], 0) + 1
    print(json.dumps({"records": len(examples), "categories": counts, "output": str(out)}, indent=2))


if __name__ == "__main__":
    main()
