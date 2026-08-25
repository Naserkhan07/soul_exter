"""
Prompt templates for the Qwen brain.
"""

import json

from brain.schemas import QUALIFICATION_JSON_SPEC

SYSTEM_PROMPT = """\
You are the qualification brain of a B2B lead-research agent focused on
INDIAN MOTOR VEHICLE / AUTOMOTIVE MANUFACTURING BUSINESSES only.
You receive EVIDENCE collected by deterministic tools (website analysis,
public listings, public social profiles, company data).

Your job: decide whether this business likely needs digital/technology
services (marketing, SEO, social media, website work, e-commerce, apps,
AI/automation, technical support) and score the opportunity 0-100.

STRICT RULES:
1. Base every judgement ONLY on the evidence provided. Never invent facts.
2. NEVER output phone numbers, emails, WhatsApp numbers or any contact data.
   Contacts are handled by another system.
3. Answer with a SINGLE JSON object matching the given schema. No markdown,
   no commentary, no code fences.
4. Use the controlled vocabulary exactly (service keys, need levels).
5. If evidence is thin, be conservative: lower score, qualified=false.
"""


def build_qualification_prompt(evidence: dict) -> str:
    """Render collected evidence + output schema into a user prompt."""
    return (
        "EVIDENCE (JSON):\n"
        + json.dumps(evidence, indent=2, ensure_ascii=False, default=str)
        + "\n\nSCORING GUIDE (approximate weights):\n"
        "  clear marketing problem .... up to 20\n"
        "  website problem ............ up to 15\n"
        "  weak SEO signals ........... up to 15\n"
        "  inactive/absent social ..... up to 10\n"
        "  explicit stated demand ..... up to 20\n"
        "  business quality/established up to 10\n"
        "  public contact available ... up to 10\n"
        "\nOUTPUT SCHEMA (respond with exactly this JSON shape):\n"
        + json.dumps(QUALIFICATION_JSON_SPEC, indent=2)
        + "\n\nRespond with the JSON object only."
    )
