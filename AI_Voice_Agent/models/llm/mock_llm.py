"""Mock LLM — fully offline, deterministic, multilingual-aware.

Used when provider is "mock" so the ENTIRE agent (task, memory, rules,
multilingual, barge-in) can be tested with no API keys and no GPU.

It implements a small subset of a real model:
  * language detection (en/hi/ur/te/ar/es/fr/de + fallback)
  * greeting / goodbye handling
  * recall from conversation memory ("what did I say my name was")
  * knowledge retrieval by keyword matching against the task profile
  * out-of-scope redirect
All responses are returned in the SAME language as the person's message.
"""

from __future__ import annotations

import re

from ..base import LLMBase, LLMRequest

# --------------------------------------------------------------------------
# Lightweight language detection (character based).
# --------------------------------------------------------------------------
_SCRIPTS = {
    "hi": r"[\u0900-\u097F]",        # Devanagari  -> Hindi/Marathi/Nepali
    "ur": r"[\u0600-\u06FF]",        # Arabic script
    "ar": r"[\u0600-\u06FF\u0750-\u077F]",
    "te": r"[\u0C00-\u0C7F]",        # Telugu
    "ta": r"[\u0B80-\u0BFF]",        # Tamil
    "bn": r"[\u0980-\u09FF]",        # Bengali
    "ru": r"[\u0400-\u04FF]",        # Cyrillic
    "el": r"[\u0370-\u03FF]",        # Greek
    "ja": r"[\u3040-\u30FF\u4E00-\u9FFF]",
    "ko": r"[\uAC00-\uD7AF]",
    "zh": r"[\u4E00-\u9FFF]",
}

_ROMAN_WORDS = {
    "en": {"hello", "hi", "how", "what", "you", "your", "name", "the", "and", "is",
           "i", "want", "price", "services", "business", "lead", "call", "tell"},
    "ur": {"aap", "kya", "hai", "hain", "naam", "kia", "bara", "ma", "mujhe", "is",
           "samjhen", "baat", "karo", "nahi", "sab", "zara"},
    "hi": {"aap", "kya", "hai", "hain", "naam", "kiya", "baare", "mein", "mujhe",
           "samajhna", "nahi", "main", "boliye", "batao"},
    "te": {"maku", "meeku", "enti", "emiti", "endi", "maku", "kaavaali", "appudu",
           "ippudu", "maku", "ma", "gurinchi", "cheppandi", "telugu"},
    "ar": {"marhaba", "shukran", "ma", "howa", "ana", "anta", "kam", "hadha"},
}


def detect_language(text: str) -> str:
    """Return a BCP-47 code for the dominant script/language."""
    text = text.strip()
    if not text:
        return "en"
    # 1) strong script signal
    for lang, pat in _SCRIPTS.items():
        hits = len(re.findall(pat, text))
        if hits >= 2:
            # Urdu/Arabic share the Arabic script — distinguish by keywords
            if lang == "ur":
                return "ar" if _roman_hit(text, "ar") else "ur"
            return lang
    # 2) Latin script -> romanised keyword vote
    scores = {lang: sum(w in text.lower().split() for w in words)
              for lang, words in _ROMAN_WORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "en"


def _roman_hit(text: str, lang: str) -> bool:
    return any(w in text.lower() for w in _ROMAN_WORDS[lang])


_GREETINGS = re.compile(r"\b(hello|hi|hey|namaste|salam|marhaba|assalam|hola|bonjour)\b", re.I)
_GOODBYES = re.compile(r"\b(bye|goodbye|end|stop|hang up|alvida|khuda|dismiss)\b", re.I)
_NAME_SAY = re.compile(r"my name is ([a-z][a-z .'-]*)", re.I)
_NAME_INTRO = re.compile(r"\b(my name is|i[' ]m)\s+([a-z][a-z .'-]*)", re.I)
# Words that look like a name but are really the start of a statement.
_NAME_STOP = {"interested", "calling", "looking", "looking", "from", "about",
              "calling", "asking", "wondering", "just", "very", "really",
              "here", "new", "with", "in", "on", "at"}
_NAME_ASK = re.compile(r"what (was|is|did i say|did i tell).*name", re.I)
_ASKING = re.compile(
    r"(\?|what|how|who|where|when|why|tell|explain|price|cost|services|about"
    r"|kya|kyun|kaise|kaun|kab|kahan"      # Hindi/Urdu (romanised)
    r"|enti|elaa|emiti|enduku|evvaru|eppudu"  # Telugu (romanised)
    r"|کیا|کیون|کیسے|کون|کب|کہاں"          # Urdu
    r"|क्या|क्यों|कैसे|कौन|कब|कहाँ"        # Hindi
    r"|ఏమి|ఎలా|ఏమిటి|ఎందుకు|ఎవరు|ఎప్పుడు"  # Telugu
    r"|ما|كيف|كم|لماذا|متى|أين|هل)"         # Arabic
    , re.I)

# Translations used so the mock replies stay in-language.
_TX = {
    "en": {
        "unknown_name": "You haven't told me your name yet — what's your name?",
        "recall": "You said your name is {name}.",
        "greet": "Hello! I'm an AI assistant. Nice to talk with you. How can I help today?",
        "out": "I'd love to help, but I'm here specifically to talk about {topic}. Is there something about that I can answer?",
        "no_answer": "I'm not sure about that one. Could you rephrase, or ask me about {topic}?",
        "bye": "Got it, thanks for the call! Take care. Goodbye.",
        "intro": "Sure! {answer}",
        "meet": "Nice to meet you, {name}.",
        "default": "Got it. Just so I can help best — are you asking about our {topic}?",
    },
    "hi": {
        "unknown_name": "आपने अभी तक अपना नाम नहीं बताया — आपका नाम क्या है?",
        "recall": "आपने बताया था कि आपका नाम {name} है।",
        "greet": "नमस्ते! मैं एक AI सहायक हूँ। आपसे बात करके अच्छा लगा। मैं आपकी कैसे मदद कर सकता हूँ?",
        "out": "मैं मदद करना चाहूँगा, लेकिन मैं यहाँ खासकर {topic} के बारे में बात करने के लिए हूँ। क्या इस बारे में मैं कुछ बता सकता हूँ?",
        "no_answer": "मुझे इस बारे में पक्का नहीं पता। क्या आप फिर से पूछ सकते हैं, या {topic} के बारे में पूछिए?",
        "bye": "ठीक है, कॉल के लिए धन्यवाद! अपना ख्याल रखना। अलविदा।",
        "intro": "ज़रूर! {answer}",
        "meet": "आपसे मिलकर अच्छा लगा, {name}।",
        "default": "समझ गया। बेहतर मदद के लिए — क्या आप हमारे {topic} के बारे में पूछ रहे हैं?",
    },
    "ur": {
        "unknown_name": "آپ نے ابھی تک اپنا نام نہیں بتایا — آپ کا نام کیا ہے؟",
        "recall": "آپ نے بتایا تھا کہ آپ کا نام {name} ہے۔",
        "greet": "السلام علیکم! میں ایک AI معاون ہوں۔ آپ سے بات کر کے اچھا لگا۔ میں آپ کی کیا مدد کر سکتا ہوں؟",
        "out": "میں مدد کرنا چاہوں گا، لیکن میں یہاں خاص طور پر {topic} کے بارے میں بات کرنے کے لیے ہوں۔ کیا اس بارے میں کچھ بتا سکتا ہوں؟",
        "no_answer": "مجھے اس بارے میں یقین نہیں۔ کیا آپ دوبارہ پوچھ سکتے ہیں، یا {topic} کے بارے میں پوچھیں؟",
        "bye": "ٹھیک ہے، کال کے لیے شکریہ! اپنا خیال رکھیں۔ خدا حافظ۔",
        "intro": "ضرور! {answer}",
        "meet": "آپ سے مل کر خوشی ہوئی، {name}۔",
        "default": "سمجھ گیا۔ بہتر مدد کے لیے — کیا آپ ہمارے {topic} کے بارے میں پوچھ رہے ہیں؟",
    },
    "te": {
        "unknown_name": "మీరు ఇంకా మీ పేరు చెప్పలేదు — మీ పేరు ఏమిటి?",
        "recall": "మీరు చెప్పారు మీ పేరు {name} అని.",
        "greet": "నమస్కారం! నేను AI అసిస్టెంట్. మీతో మాట్లాడటం ఆనందంగా ఉంది. నేను మీకు ఎలా సహాయం చేయగలను?",
        "out": "నేను సహాయం చేయాలనుకుంటున్నాను, కానీ నేను ఇక్కడ ప్రత్యేకంగా {topic} గురించి మాట్లాడటానికి ఉన్నాను. దాని గురించి ఏమైనా చెప్పగలనా?",
        "no_answer": "దీని గురించి నాకు ఖచ్చితంగా తెలియదు. మీరు మళ్ళీ అడగగలరా, లేదా {topic} గురించి అడగండి?",
        "bye": "సరే, కాల్ కి ధన్యవాదాలు! జాగ్రత్త. వీడ్కోలు.",
        "intro": "ఖచ్చితంగా! {answer}",
        "meet": "మిమ్మల్ని కలవడం ఆనందంగా ఉంది, {name}.",
        "default": "సరే. మంచి సహాయం కోసం — మీరు మా {topic} గురించి అడుగుతున్నారా?",
    },
    "ar": {
        "unknown_name": "لم تخبرني باسمك بعد — ما اسمك؟",
        "recall": "لقد قلت إن اسمك {name}.",
        "greet": "مرحباً! أنا مساعد ذكاء اصطناعي. سعيد بالحديث معك. كيف يمكنني مساعدتك اليوم؟",
        "out": "أود المساعدة، لكنني هنا خصيصاً للتحدث عن {topic}. هل هناك شيء أستطيع الإجابة عنه حول هذا؟",
        "no_answer": "لست متأكداً من ذلك. هل يمكنك إعادة الصياغة، أو اسأل عن {topic}؟",
        "bye": "حسناً، شكراً على المكالمة! اعتنِ بنفسك. وداعاً.",
        "intro": "بالتأكيد! {answer}",
        "meet": "سررت بلقائك يا {name}.",
        "default": "فهمت. لتساعدني بشكل أفضل — هل تسأل عن {topic} لدينا؟",
    },
}


class MockLLM(LLMBase):
    name = "mock"

    def __init__(self) -> None:
        pass

    def complete(self, req: LLMRequest) -> str:
        last_user = ""
        user_msgs = [m for m in req.messages if m["role"] == "user"]
        if user_msgs:
            last_user = user_msgs[-1]["content"].strip()
        lang = detect_language(last_user) if req.language in ("auto", "") else req.language
        lang = lang if lang in _TX else "en"
        tx = _TX[lang]
        topic = self._topic_from_system(req.system)

        if _GOODBYES.search(last_user):
            return tx["bye"]
        if _GREETINGS.search(last_user) and len(last_user.split()) <= 6:
            return tx["greet"]

        # recall: person asks for their own name
        if _NAME_ASK.search(last_user):
            name = self._find_name(req.messages)
            return tx["recall"].format(name=name) if name else tx["unknown_name"]

        # person introduces themselves by name
        nm = _NAME_INTRO.search(last_user)
        if nm and nm.group(2):
            _n = nm.group(2).strip().rstrip(".")
            if _n and _n.split()[0].lower() not in _NAME_STOP:
                return tx["meet"].format(name=_n)

        is_question = bool(_ASKING.search(last_user))

        # Explicit intents for the most common questions (clearer than keyword
        # matching alone). These read a named knowledge section directly.
        intent = self._match_intent(last_user)
        if intent:
            answer = self._section_text(req.system, intent)
            if answer and is_question:
                return tx["intro"].format(answer=answer)
            if answer:
                return answer

        # knowledge answer
        answer = self._retrieve(last_user, topic, req.system)
        if answer:
            if is_question:
                return tx["intro"].format(answer=answer)
            return answer

        # a question with no matching knowledge -> honest "not sure"
        if is_question:
            return tx["no_answer"].format(topic=topic)

        # out of scope redirect (non-question not about the topic)
        if not self._mentions_topic(last_user, topic):
            return tx["out"].format(topic=topic)
        return tx["default"].format(topic=topic)

    # ---------------- helpers ----------------
    @staticmethod
    def _match_intent(text: str) -> str | None:
        """Map a question to a knowledge section title (exact intents)."""
        t = text.lower()
        if re.search(r"\b(who are you|what company|about you|who is this|who's this|what is maqsusi)\b", t):
            return "company"
        if re.search(r"\b(how much|cost|price|pricing|rate|pod|pods)\b", t):
            return "pricing"
        if re.search(r"\b(mendix|low-?code|low code)\b", t):
            return "services"
        if re.search(r"\b(industries|sector|verticals|which industry|automotive|aerospace|banking)\b", t):
            return "industries"
        if re.search(r"\b(polarion)\b", t):
            return "polarion"
        if re.search(r"\b(service|offer|provide|do you do|do you build|what do you)\b", t):
            return "services"
        return None

    def _section_text(self, system: str, title: str) -> str | None:
        for t, body in self._knowledge_sections(system):
            if t.strip().lower() == title.strip().lower():
                lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
                return " ".join(lines[:4])[:500] if lines else None
        return None

    def _find_name(self, messages: list[dict]) -> str | None:
        for m in messages:
            if m["role"] == "user":
                mt = _NAME_SAY.search(m["content"])
                if mt:
                    return mt.group(1).strip()
        return None

    def _topic_from_system(self, system: str) -> str:
        for line in system.splitlines():
            if "## ROLE / TASK" in line or line.startswith("TASK"):
                continue
        # grab the first task sentence
        m = re.search(r"(?:about|discuss|talk about|subject)[:\s]+([A-Za-z][^.\n]+)", system, re.I)
        if m:
            return m.group(1).strip().rstrip(".")
        return "our services"

    def _mentions_topic(self, text: str, topic: str) -> bool:
        words = set(re.findall(r"\w+", topic.lower()))
        return bool(words & set(re.findall(r"\w+", text.lower())))

    @staticmethod
    def _knowledge_sections(system: str) -> list[tuple[str, str]]:
        """Parse '### <title>\\n<body>' blocks out of the system prompt."""
        sections: list[tuple[str, str]] = []
        current_title: str | None = None
        current_body: list[str] = []
        for line in system.splitlines():
            if line.startswith("### "):
                if current_title:
                    sections.append((current_title, "\n".join(current_body)))
                current_title = line[4:].strip()
                current_body = []
            elif current_title is not None:
                current_body.append(line)
        if current_title:
            sections.append((current_title, "\n".join(current_body)))
        return sections

    def _retrieve(self, query: str, topic: str, req_system: str) -> str | None:
        """Keyword-match the query against task knowledge; return best section.

        Title words are weighted heavily, so e.g. "what is Polarion?" strongly
        prefers a knowledge section titled "POLARION".
        """
        kws = {w for w in re.findall(r"\w+", query.lower()) if len(w) > 2}
        if not kws:
            return None
        best_section = None
        best_score = 0
        for title, body in self._knowledge_sections(req_system):
            title_words = set(re.findall(r"\w+", title.lower()))
            body_words = set(re.findall(r"\w+", body.lower() if body else ""))
            # Deprioritise the FAQ for open knowledge questions, since it holds
            # generic Q&A that tends to match everything.
            title_lower = title.lower()
            faq_penalty = -2 if ("faq" in title_lower or "q:" in body.lower()[:400]) else 0
            # Strong boost when the query directly names the section (e.g. a
            # query containing "polarion" -> section titled "polarion").
            title_hit = len(kws & title_words)
            score = (len(kws & body_words) + 20 * title_hit + faq_penalty)
            if score > best_score:
                best_score, best_section = score, (title, body)
        if best_section and best_score >= 1:
            title, body = best_section
            lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
            if lines:
                return " ".join(lines[:4])[:500]
        return None
