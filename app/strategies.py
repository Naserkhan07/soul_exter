"""Revenue strategy portfolio.

Strategies describe what Automaton may build and how far automation can go. A
marketplace name is never permission to automate uploads; operator_review means
account creation, terms acceptance, and publishing stay with the legal operator.
"""

STRATEGIES = [
    {"slug": "local-growth-pack", "name": "Local business growth pack", "category": "service", "channels": ["own_site"], "buildability": 100, "speed": 95, "risk": 10, "automation": "full"},
    {"slug": "developer-script", "name": "Developer utility script", "category": "code", "channels": ["own_site", "Gumroad", "CodeCanyon"], "buildability": 90, "speed": 90, "risk": 35, "automation": "operator_review"},
    {"slug": "website-template", "name": "Website template", "category": "code", "channels": ["own_site", "Gumroad", "ThemeForest"], "buildability": 88, "speed": 82, "risk": 30, "automation": "operator_review"},
    {"slug": "spreadsheet-template", "name": "Spreadsheet template", "category": "template", "channels": ["own_site", "Gumroad", "Etsy"], "buildability": 95, "speed": 92, "risk": 15, "automation": "operator_review"},
    {"slug": "digital-template", "name": "Business digital template", "category": "template", "channels": ["own_site", "Gumroad", "Etsy"], "buildability": 96, "speed": 94, "risk": 12, "automation": "operator_review"},
    {"slug": "developer-reference", "name": "Developer reference pack", "category": "guide", "channels": ["own_site", "Gumroad"], "buildability": 94, "speed": 90, "risk": 15, "automation": "operator_review"},
    {"slug": "research-report", "name": "Specialized research report", "category": "research", "channels": ["own_site", "Gumroad"], "buildability": 82, "speed": 65, "risk": 35, "automation": "operator_review"},
    {"slug": "specialized-calculator", "name": "Specialized calculator", "category": "tool", "channels": ["own_site"], "buildability": 88, "speed": 80, "risk": 25, "automation": "operator_review"},
    {"slug": "micro-tool", "name": "Small online utility", "category": "tool", "channels": ["own_site"], "buildability": 85, "speed": 78, "risk": 30, "automation": "operator_review"},
    {"slug": "automation-workflow", "name": "Automation workflow pack", "category": "code", "channels": ["own_site", "Gumroad"], "buildability": 82, "speed": 72, "risk": 35, "automation": "operator_review"},
    {"slug": "public-dataset", "name": "Public-data pack", "category": "data", "channels": ["own_site", "Gumroad"], "buildability": 65, "speed": 45, "risk": 55, "automation": "operator_review"},
    {"slug": "browser-extension", "name": "Browser extension", "category": "software", "channels": ["Chrome Web Store"], "buildability": 65, "speed": 50, "risk": 60, "automation": "operator_review"},
    {"slug": "api-service", "name": "Specialized API", "category": "software", "channels": ["own_site", "RapidAPI"], "buildability": 62, "speed": 45, "risk": 60, "automation": "operator_review"},
    {"slug": "browser-game", "name": "Simple browser game", "category": "game", "channels": ["own_site", "itch.io", "CrazyGames", "Poki"], "buildability": 58, "speed": 42, "risk": 50, "automation": "operator_review"},
    {"slug": "micro-saas", "name": "Micro-SaaS", "category": "software", "channels": ["own_site"], "buildability": 50, "speed": 30, "risk": 70, "automation": "operator_review"},
    {"slug": "affiliate-directory", "name": "Niche affiliate directory", "category": "website", "channels": ["own_site"], "buildability": 68, "speed": 40, "risk": 65, "automation": "operator_review"},
]


def rank_strategies(metrics: dict[str, dict] | None = None) -> list[dict]:
    metrics = metrics or {}
    ranked = []
    for item in STRATEGIES:
        observed = metrics.get(item["slug"], {})
        revenue = int(observed.get("revenue_cents", 0))
        views = int(observed.get("views", 0))
        sales = int(observed.get("sales", 0))
        evidence_bonus = min(35, revenue // 10_000 + sales * 5)
        no_sale_penalty = 15 if views >= 100 and sales == 0 else 0
        score = round(item["buildability"] * .45 + item["speed"] * .35 + (100 - item["risk"]) * .20 + evidence_bonus - no_sale_penalty)
        ranked.append({**item, "score": max(0, min(100, score)), "metrics": {"views": views, "sales": sales, "revenue_cents": revenue},
                       "next_action": "build_and_test" if item["automation"] == "full" else "prepare_for_operator_review"})
    return sorted(ranked, key=lambda value: (-value["score"], value["name"]))
