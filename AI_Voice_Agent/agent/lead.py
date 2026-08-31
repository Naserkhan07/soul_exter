"""Lead capture.

The agent's goal on a call is to convert it into a successful LEAD for the
business: find out who the person is, how to reach them, and what they are
interested in. This module scans each turn for that information and keeps a
live lead record the GUI can display.

A lead is "captured" when we have at least a name AND a contact (phone/email)
AND an interest. The agent is instructed to politely collect these and confirm
a follow-up.
"""

from __future__ import annotations

import re

_NAME = re.compile(r"(?:my name is|my name's|i[' ]m|i am|this is)\s+([A-Za-z][A-Za-z'.\-]*(?:\s+[A-Za-z][A-Za-z'.\-]*)?)", re.I)
# Words that follow an intro phrase but are not really part of the name.
_NAME_STOP = {"and", "or", "from", "about", "looking", "want", "wanted", "need",
              "needed", "interested", "calling", "contact", "here", "just",
              "very", "really", "new", "with", "for", "the", "a", "an",
              "please", "is", "i", "we", "our", "my"}
_PHONE = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,5}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{3,4}(?:\s*(?:ext\.?|x)\s*\d+)?", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

# Interest keywords -> readable label
_INTERESTS = [
    (re.compile(r"polarion", re.I), "Polarion (ALM)"),
    (re.compile(r"website|web ?site|site", re.I), "Website"),
    (re.compile(r"seo|google|rank", re.I), "SEO"),
    (re.compile(r"marketing|ads|advert", re.I), "Digital Marketing"),
    (re.compile(r"app|application|mobile", re.I), "Apps"),
    (re.compile(r"ai|artificial intelligence|workflow|automation|voice agent", re.I),
     "AI Workflows / Automation"),
    (re.compile(r"digital services|digital", re.I), "Digital Services"),
]


class Lead:
    def __init__(self) -> None:
        self.name: str = ""
        self.phone: str = ""
        self.email: str = ""
        self.interest: str = ""
        self.captured: bool = False
        self.milestone_log: list[str] = []

    @property
    def completeness(self) -> float:
        """0.0 -> 1.0 based on how much of a lead we've captured."""
        score = 0.0
        if self.name:
            score += 0.35
        if self.phone or self.email:
            score += 0.35
        if self.interest:
            score += 0.30
        return round(score, 2)

    def missing(self) -> list[str]:
        out = []
        if not self.name:
            out.append("their name")
        if not (self.phone or self.email):
            out.append("a contact number / email")
        if not self.interest:
            out.append("which service they're interested in")
        return out

    def update(self, text: str) -> list[str]:
        """Scan one turn (person's speech); return new milestone messages."""
        changes: list[str] = []
        m = _NAME.search(text)
        if m and not self.name:
            raw = m.group(1).strip().rstrip(".,!?")
            words = [w for w in raw.split() if w.lower() not in _NAME_STOP]
            if words:
                self.name = " ".join(words[:2])
                changes.append(f"✔ Got the person's name: {self.name}")

        phone = self._find_phone(text)
        if phone and not (self.phone or self.email):
            self.phone = phone
            changes.append(f"✔ Got a contact number: {phone}")

        e = _EMAIL.search(text)
        if e and not (self.phone or self.email):
            self.email = e.group(0)
            changes.append(f"✔ Got an email: {self.email}")

        for pat, label in _INTERESTS:
            if pat.search(text) and not self.interest:
                self.interest = label
                changes.append(f"✔ Interested in: {label}")
                break

        if not self.captured and self.completeness >= 1.0:
            self.captured = True
            changes.append(
                f"🎯 LEAD CAPTURED! Name: {self.name} | Contact: {self.phone or self.email} "
                f"| Interest: {self.interest}")

        return changes

    def _find_phone(self, text: str) -> str:
        # A real phone number is >6 digits.
        for m in _PHONE.finditer(text):
            digits = re.sub(r"\D", "", m.group(0))
            if 7 <= len(digits) <= 15:
                return m.group(0).strip().rstrip(".,")
        return ""

    def to_dict(self) -> dict:
        return {
            "name": self.name, "phone": self.phone, "email": self.email,
            "interest": self.interest, "captured": self.captured,
            "completeness": self.completeness,
        }
