"""
Executor — investigates ONE candidate business end-to-end.

    candidate dict
      -> website analysis (tools/website_analyzer)
      -> public contact extraction (tools/contacts)
      -> decision-maker hints (tools/linkedin, self-published only)
      -> evidence dict
      -> Qwen qualification (brain/decision_engine)
      -> Lead object (database/models)

No messaging. No contacting. Research only.
"""

import logging

from bs4 import BeautifulSoup

from brain.decision_engine import DecisionEngine
from database.models import Lead, apply_needs
from database.deduplication import identity_key
from tools.browser import fetch
from tools.contacts import find_public_contacts
from tools.linkedin import extract_decision_maker, extract_linkedin_urls
from tools.website_analyzer import analyze_website, summarize_issues

log = logging.getLogger("agent.executor")


class Executor:
    def __init__(self, engine: DecisionEngine | None = None):
        self.engine = engine or DecisionEngine()

    # ------------------------------------------------------------------ #
    def investigate(self, candidate: dict) -> tuple:
        """
        Returns (lead: Lead | None, qualification: Qualification | None).
        lead is None when the business doesn't qualify.
        """
        name = candidate.get("business_name", "").strip()
        website = (candidate.get("website") or "").strip()
        log.info("Investigating: %s (%s)", name or "?", website or "no site")

        evidence = {
            "business_name": name,
            "business_category": candidate.get("business_category", ""),
            "location": candidate.get("address", "")
                        or candidate.get("query_location", ""),
            "website": website,
            "discovery_source": candidate.get("source", ""),
            "signals": {
                "rating": candidate.get("rating"),
                "review_count": candidate.get("review_count"),
                "explicit_demand": candidate.get("explicit_demand", ""),
                "company_size": candidate.get("company_size", ""),
            },
        }

        analysis, contacts, person = {}, {}, {}
        linkedin_found = candidate.get("linkedin", "")

        if website:
            analysis = analyze_website(website)
            evidence["website_analysis"] = analysis
            evidence["website_issues"] = summarize_issues(analysis)

            contacts = find_public_contacts(
                website, analysis.get("contact_pages", []))

            socials = dict(analysis.get("social_links", {}))
            socials.update(contacts.get("socials", {}))
            evidence["social"] = {
                "profiles_found": len(socials),
                "platforms": sorted(socials),
            }
            contacts["socials"] = socials
            if not linkedin_found:
                linkedin_found = socials.get("linkedin", "")

            # self-published decision maker (about/contact page text)
            person = self._find_decision_maker(website, analysis)
        else:
            evidence["website_analysis"] = {"reachable": False}
            evidence["website_issues"] = ["no website found"]
            evidence["social"] = {"profiles_found": 0, "platforms": []}

        # contacts from the discovery source itself (e.g. Maps listing phone)
        if candidate.get("phone") and not contacts.get("phone"):
            contacts["phone"] = candidate["phone"]

        evidence["contacts"] = {
            "phone": contacts.get("phone", ""),
            "whatsapp": contacts.get("whatsapp", ""),
            "email": contacts.get("email", ""),
            "linkedin": linkedin_found,
            "website": website,
        }

        # ---- Qwen decides -------------------------------------------------
        qualification = self.engine.qualify(evidence)
        log.info("Qualification: score=%s qualified=%s (%s)",
                 qualification.lead_score, qualification.qualified, name)

        if not qualification.qualified:
            return None, qualification

        lead = self._build_lead(candidate, contacts, person,
                                linkedin_found, qualification)
        return lead, qualification

    # ------------------------------------------------------------------ #
    def _find_decision_maker(self, website: str, analysis: dict) -> dict:
        """Look for a self-published founder/owner mention on about pages."""
        pages = [p for p in analysis.get("contact_pages", [])
                 if "about" in p.lower()][:1]
        pages.append(website)
        for page in pages:
            res = fetch(page)
            if not res.ok:
                continue
            text = BeautifulSoup(res.html, "lxml").get_text(" ", strip=True)
            person = extract_decision_maker(text)
            if person["person_name"]:
                li = extract_linkedin_urls(res.html)
                person["linkedin_profile"] = (
                    li["profiles"][0] if li["profiles"] else "")
                return person
        return {"person_name": "", "person_role": "", "linkedin_profile": ""}

    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_lead(candidate, contacts, person, linkedin, qualification) -> Lead:
        socials = contacts.get("socials", {})
        source_urls = [u for u in [
            candidate.get("source_url", ""),
            *(contacts.get("pages_checked") or []),
        ] if u]

        loc = candidate.get("location_meta", {})
        address = candidate.get("address", "")

        lead = Lead(
            lead_id=identity_key(
                name=candidate.get("business_name", ""),
                website=candidate.get("website", ""),
                phone=contacts.get("phone", ""),
                city=loc.get("city", ""),
                linkedin=linkedin,
            ),
            business_name=candidate.get("business_name", ""),
            business_category=candidate.get("business_category", ""),
            person_name=person.get("person_name", ""),
            person_role=person.get("person_role", ""),
            state=loc.get("state", ""),
            district=loc.get("district", ""),
            city=loc.get("city", ""),
            locality=loc.get("locality", ""),
            full_location=address or loc.get("query_location", ""),
            phone=contacts.get("phone", ""),
            whatsapp=contacts.get("whatsapp", ""),
            email=contacts.get("email", ""),
            website=candidate.get("website", ""),
            linkedin=linkedin or person.get("linkedin_profile", ""),
            instagram=socials.get("instagram", ""),
            facebook=socials.get("facebook", ""),
            youtube=socials.get("youtube", ""),
            twitter=socials.get("twitter", ""),
            source_urls=list(dict.fromkeys(source_urls)),
            detected_problems=qualification.detected_problems,
            recommended_services=qualification.recommended_services,
            lead_score=qualification.lead_score,
            evidence_reason=qualification.reason,
            discovery_source=candidate.get("source", ""),
        )
        apply_needs(lead, qualification.needs)
        return lead
