"""Pure parsing and scoring helpers for the /cold-email skill.

Standard library only, no network. Everything here is covered by tests/.
"""
from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass, field

UTC = dt.timezone.utc

# ---------------------------------------------------------------- LinkedIn dates

_ACTIVITY_RE = re.compile(r"(?:activity|ugcPost|share)[-:](\d{18,20})")


def linkedin_post_date(url: str) -> dt.datetime | None:
    """Post time from a public LinkedIn post URL.

    The activity id is a snowflake: the top 41 bits are epoch milliseconds,
    so ``id >> 22`` gives the creation time. Verified on real posts whose
    search snippets said "8 days ago" (31 Oct 2026 -> 24 Oct 2026).
    """
    m = _ACTIVITY_RE.search(url or "")
    if not m:
        return None
    ms = int(m.group(1)) >> 22
    if not 1_262_304_000_000 < ms < 4_102_444_800_000:  # 2010..2100
        return None
    return dt.datetime.fromtimestamp(ms / 1000, UTC)


# "8 days ago", "vor 3 Tagen", and LinkedIn's "2w •" / "3mo ·" shorthand
_REL_LONG = re.compile(r"\b(\d+)\s*(minute|min|hour|hr|day|week|wk|month|year|yr)s?\s+ago\b", re.I)
_REL_DE = re.compile(r"\bvor\s+(\d+)\s*(Minute|Stunde|Tag|Woche|Monat|Jahr)(?:n|en|e)?\b", re.I)
_REL_SHORT = re.compile(r"(?<![\w.])(\d+)\s?(mo|h|d|w|y)\s*[•·]", re.I)
_UNIT_DAYS = {
    "minute": 1 / 1440, "min": 1 / 1440, "hour": 1 / 24, "hr": 1 / 24, "h": 1 / 24,
    "day": 1, "d": 1, "week": 7, "wk": 7, "w": 7, "month": 30, "mo": 30, "year": 365, "yr": 365, "y": 365,
    "stunde": 1 / 24, "tag": 1, "woche": 7, "monat": 30, "jahr": 365,
}


def relative_age_days(text: str) -> float | None:
    """Age in days from snippet text like "8 days ago", "vor 3 Tagen", "2w •"."""
    for rx in (_REL_LONG, _REL_DE, _REL_SHORT):
        m = rx.search(text or "")
        if m:
            return int(m.group(1)) * _UNIT_DAYS[m.group(2).lower()]
    return None


def post_age_days(url: str, snippet: str = "", now: dt.datetime | None = None) -> float | None:
    now = now or dt.datetime.now(UTC)
    d = linkedin_post_date(url)
    if d:
        return (now - d).total_seconds() / 86400
    return relative_age_days(snippet)


# ---------------------------------------------------------------- emails

_AT = r"(?:@|\s?\[at\]\s?|\s?\(at\)\s?|\s?\{at\}\s?|\s+at\s+|\s?\[ät\]\s?)"
_DOT = r"(?:\.|\s?\[dot\]\s?|\s?\(dot\)\s?|\s?\{dot\}\s?|\s+dot\s+|\s?\[punkt\]\s?|\s?\(punkt\)\s?)"
_LOCAL = r"[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}"
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_EMAIL_RE = re.compile(rf"(?<![\w.+-])({_LOCAL}){_AT}((?:{_LABEL}{_DOT})+[A-Za-z]{{2,24}})(?![\w-])", re.I)
_DOT_SPLIT = re.compile(_DOT, re.I)

# never cold-email these
BLOCKED_LOCAL = {
    "noreply", "no-reply", "donotreply", "do-not-reply", "datenschutz", "privacy", "dpo",
    "dataprotection", "data-protection", "abuse", "postmaster", "webmaster", "hostmaster",
    "unsubscribe", "bounce", "mailer-daemon", "support", "billing", "invoice", "rechnung",
    "press", "presse", "media", "legal", "compliance", "security",
}
BLOCKED_DOMAINS = {"example.com", "example.org", "domain.com", "email.com", "sentry.io", "wixpress.com"}
_ASSET_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js"}


def _clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"mailto:", " ", text, flags=re.I)
    return text


def extract_emails(text: str) -> list[str]:
    """All plausible emails in text, de-obfuscated, lowercase, in order, unique.

    Handles ``name@x.de``, ``name [at] x [dot] de``, ``name(at)x.de``, HTML
    entities and mailto links. Drops no-reply/privacy/abuse style inboxes.
    """
    out: list[str] = []
    for m in _EMAIL_RE.finditer(_clean_text(text)):
        local = m.group(1).strip(".").lower()
        domain = ".".join(p for p in _DOT_SPLIT.split(m.group(2).lower()) if p)
        tld = domain.rsplit(".", 1)[-1]
        if tld in _ASSET_TLDS or domain in BLOCKED_DOMAINS:
            continue
        if local in BLOCKED_LOCAL or local.split("+")[0] in BLOCKED_LOCAL:
            continue
        # "x at y dot com" in prose: require a dot in the domain and no spaces left
        if " " in local or "." not in domain or not re.search(r"[a-z]", domain.split(".")[0]):
            continue
        email = f"{local}@{domain}"
        if email not in out:
            out.append(email)
    return out


def email_kind(email: str) -> str:
    """'person' (firstname.lastname), 'jobs' (jobs@, careers@), 'generic' (info@)."""
    local = email.split("@", 1)[0]
    if re.fullmatch(r"(jobs?|careers?|karriere|bewerbung(en)?|recruiting|hr|talent|hiring|people)", local):
        return "jobs"
    if re.fullmatch(r"(info|hello|hallo|hi|contact|kontakt|office|mail|team|service|anfrage)", local):
        return "generic"
    return "person"


KIND_RANK = {"person": 0, "jobs": 1, "generic": 2}


# ---------------------------------------------------------------- Impressum

_NAME = r"(?:Dr\.\s*|Prof\.\s*)*[A-ZÄÖÜ][a-zäöüßéèáçñ'-]+(?:\s+(?:von|van|de|der|zu)\s+|\s+|-)[A-ZÄÖÜ][a-zäöüßéèáçñ'-]+(?:-[A-ZÄÖÜ][a-zäöüß'-]+)?"
_MD_LABEL = re.compile(
    r"(?:Geschäftsführ(?:er|erin|ung|ende(?:r)?)|Vertretungsberechtigte(?:r)?\s+Geschäftsführer(?:in)?|"
    r"Vertreten\s+durch(?:\s+(?:den|die)\s+Geschäftsführer(?:in)?)?|Managing\s+Directors?|"
    r"Represented\s+by(?:\s+the\s+Managing\s+Directors?)?|CEO|Vorstand)\s*[:\-–]?\s*",
    re.I,
)
_STOP = re.compile(r"\b(Registergericht|Amtsgericht|Handelsregister|HRB|USt|Umsatzsteuer|Sitz|Register|Tel|Telefon|Phone|E-?Mail|Kontakt|Contact|Verantwortlich|VAT|Court|Commercial|Registered|Registration|Address|Anschrift|Straße|Strasse|Street|Germany|Deutschland)\b", re.I)


# Words that look like "Firstname Lastname" in page text but are not people.
_NOT_NAME_WORDS = {
    "legal", "notice", "code", "factory", "imprint", "impressum", "privacy", "policy", "data", "protection", "terms",
    "service", "services", "contact", "kontakt", "team", "company", "group", "board", "directors", "director",
    "managing", "management", "home", "about", "careers", "jobs", "news", "press", "cookie", "cookies", "settings",
    "datenschutz", "geschäftsführer", "geschäftsführung", "vorstand", "aufsichtsrat", "vorsitzender", "angaben",
    "gemäß", "haftung", "inhalte", "links", "urheberrecht", "verantwortlich", "online", "digital", "solutions",
    "technologies", "software", "systems", "labs", "studio", "gmbh", "holding", "partner", "partners", "chief",
    "executive", "officer", "founder", "founders", "berlin", "münchen", "munich", "hamburg", "köln", "frankfurt",
}


def _is_person_name(name: str) -> bool:
    words = [w.lower().strip(".") for w in re.split(r"[\s-]+", name) if w.strip(".").lower() not in {"dr", "prof"}]
    return len(words) >= 2 and not any(w in _NOT_NAME_WORDS for w in words)


@dataclass
class Impressum:
    company: str | None = None
    managing_directors: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)


def html_to_text(page: str) -> str:
    page = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", page or "")
    # keep mailto targets visible before stripping tags
    page = re.sub(r'(?i)href=["\']mailto:([^"\'?]+)', r'> \1 <a ', page)
    page = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|tr|dd|dt)>", "\n", page)
    page = re.sub(r"<[^>]+>", " ", page)
    page = html.unescape(page)
    page = re.sub(r"[ \t ]+", " ", page)
    return re.sub(r"\n\s*\n+", "\n", page).strip()


def parse_impressum(text: str) -> Impressum:
    """Managing directors, company name and emails from an Impressum/imprint page (text or HTML)."""
    if "<" in text and ">" in text:
        text = html_to_text(text)
    imp = Impressum(emails=extract_emails(text))
    m = re.search(r"([A-ZÄÖÜ0-9][\w&.,' -]{1,80}?\s(?:GmbH(?:\s&\sCo\.\sKG)?|UG(?:\s\(haftungsbeschränkt\))?|AG|SE|KG|e\.V\.|Ltd\.?|Inc\.?))(?=[\s,]|$)", text)
    if m:
        imp.company = m.group(1).strip(" ,")
    for lm in _MD_LABEL.finditer(text):
        tail = text[lm.end(): lm.end() + 200]
        tail = _STOP.split(tail, 1)[0]
        tail = tail.split("\n\n", 1)[0]
        for name in re.findall(_NAME, tail):
            name = re.sub(r"\s+", " ", name).strip()
            if not _is_person_name(name):
                continue
            if name not in imp.managing_directors:
                imp.managing_directors.append(name)
    return imp


# ---------------------------------------------------------------- CV + matching

SECTION_WEIGHTS = {"experience": 1.0, "projects": 0.75, "skills": 0.5, "other": 0.25}

_HEADINGS = {
    "experience": r"(work\s+)?experience|professional\s+experience|employment|berufserfahrung|praxiserfahrung|work\s+history",
    "projects": r"projects?|projekte|side\s+projects|selected\s+projects|portfolio",
    "skills": r"(technical\s+)?skills|kenntnisse|fähigkeiten|tech\s+stack|technologies|tools",
    "other": r"summary|profile|profil|education|ausbildung|studium|certifications?|languages|sprachen|interests|awards|publications",
}


def split_cv_sections(text: str) -> dict[str, str]:
    """Split CV text into experience / projects / skills / other by heading lines."""
    sections = {k: "" for k in SECTION_WEIGHTS}
    current = "other"
    for line in (text or "").splitlines():
        s = line.strip().strip(":").strip()
        hit = None
        if 0 < len(s) <= 40:
            for name, pat in _HEADINGS.items():
                if re.fullmatch(rf"(?i)({pat})", s):
                    hit = name
                    break
        if hit:
            current = hit
            continue
        sections[current] += line + "\n"
    return sections


# Common tech / role terms. Matching is case-insensitive on word boundaries.
VOCAB = sorted({
    "python", "java", "javascript", "typescript", "go", "golang", "rust", "c++", "c#", "kotlin", "swift", "scala",
    "ruby", "php", "sql", "r", "matlab", "bash", "node.js", "react", "next.js", "vue", "angular", "svelte",
    "django", "flask", "fastapi", "spring", "spring boot", ".net", "rails", "graphql", "rest", "grpc",
    "microservices", "distributed systems", "kafka", "rabbitmq", "redis", "postgresql", "postgres", "mysql",
    "mongodb", "elasticsearch", "snowflake", "bigquery", "spark", "airflow", "dbt", "aws", "gcp", "azure",
    "docker", "kubernetes", "terraform", "ci/cd", "github actions", "linux", "llm", "llms", "rag", "langchain",
    "langgraph", "openai", "anthropic", "claude", "ai agents", "machine learning", "deep learning",
    "pytorch", "tensorflow", "scikit-learn", "nlp", "computer vision", "mlops", "data engineering",
    "data science", "pandas", "numpy", "embedded", "c", "ros", "autosar", "sap", "abap", "salesforce",
    "figma", "ux", "product management", "devops", "sre", "observability", "prometheus", "grafana",
    "android", "ios", "flutter", "react native", "html", "css", "tailwind", "webassembly",
    "hugging face", "transformers", "vector database", "prompt engineering", "fine-tuning", "cuda",
    "solidworks", "catia", "cad", "simulink", "plc", "excel", "power bi", "tableau",
})


# Short terms that are also everyday words only count in their written form ("Go", not "go").
CASE_SENSITIVE = {"go": "Go", "r": "R", "c": "C", "rest": "REST", "sap": "SAP", "ux": "UX", "ros": "ROS",
                  "cad": "CAD", "plc": "PLC", "excel": "Excel"}


def _term_re(term: str) -> re.Pattern:
    if term in CASE_SENSITIVE:
        return re.compile(rf"(?<![\w+#.-]){re.escape(CASE_SENSITIVE[term])}(?![\w+#-])")
    return re.compile(rf"(?<![\w+#.]){re.escape(term)}(?![\w+#])", re.I)


_TERM_CACHE: dict[str, re.Pattern] = {}


def has_term(text: str, term: str) -> bool:
    rx = _TERM_CACHE.get(term) or _TERM_CACHE.setdefault(term, _term_re(term))
    return bool(rx.search(text or ""))


def skills_from_section(text: str) -> list[str]:
    """Free-form skill terms from a skills section ("Languages: Go, Python, SQL")."""
    terms = []
    for line in (text or "").splitlines():
        line = re.sub(r"^[\s•*·\-–]+", "", line)
        if ":" in line:
            line = line.split(":", 1)[1]
        for part in re.split(r"[,;|•·]", line):
            part = part.strip().strip(".").strip()
            if 1 <= len(part) <= 30 and len(part.split()) <= 3 and not re.search(r"\d{4}", part):
                terms.append(part.lower())
    return terms


def cv_terms(sections: dict[str, str]) -> dict[str, float]:
    """term -> strongest section weight where the CV shows it."""
    candidates = set(VOCAB) | set(skills_from_section(sections.get("skills", "")))
    weights: dict[str, float] = {}
    for term in candidates:
        for sec, w in SECTION_WEIGHTS.items():
            if has_term(sections.get(sec, ""), term):
                weights[term] = max(weights.get(term, 0.0), w)
    return weights


@dataclass
class Match:
    score: float
    matched: list[str]
    missing: list[str]


def score_posting(cv_weights: dict[str, float], posting: str) -> Match:
    """Weighted share of the posting's terms the CV covers.

    Posting terms = known vocabulary + the CV's own skill terms found in the
    posting. Each covered term counts with the CV section weight where it
    shows up (experience 1.0, projects 0.75, skills 0.5, other 0.25).
    """
    vocab = set(VOCAB) | set(cv_weights)
    asked = sorted(t for t in vocab if has_term(posting, t))
    # "postgres" and "postgresql" or "llm"/"llms" should not double count
    asked = [t for t in asked if not any(o != t and o.startswith(t) and o in asked for o in asked)]
    if not asked:
        return Match(0.0, [], [])
    matched = [t for t in asked if t in cv_weights]
    missing = [t for t in asked if t not in cv_weights]
    got = sum(cv_weights[t] for t in matched)
    # small postings with 1-2 terms should not look like perfect matches
    score = got / max(len(asked), 4)
    return Match(round(min(score, 1.0), 3), matched, missing)


def title_matches(title: str, roles: list[str]) -> bool:
    """True if any role keyword set appears in the job title (all words of a role)."""
    t = (title or "").lower()
    for role in roles:
        words = [w for w in re.split(r"[\s/,-]+", role.lower()) if w and w not in {"and", "or", "m/w/d", "(m/w/d)"}]
        if words and all(w in t for w in words):
            return True
    return False


SENIORITY = {
    "student": r"werkstudent|working\s+student|student|intern|praktik|thesis|abschlussarbeit",
    "junior": r"junior|graduate|entry|berufseinsteiger|trainee|associate",
    "senior": r"senior|staff|principal|lead|head\s+of",
}


def seniority_ok(title: str, wanted: list[str]) -> bool:
    """Keep a job if its title fits one of the wanted levels ('mid' = no level word)."""
    if not wanted:
        return True
    t = (title or "").lower()
    found = {k for k, pat in SENIORITY.items() if re.search(pat, t)}
    if not found:
        return "mid" in wanted or "any" in wanted
    return bool(found & set(wanted))


# ---------------------------------------------------------------- drafts

BANNED_PHRASES = [
    "i am writing to express", "to whom it may concern", "any opportunities", "dear sir or madam",
    "dear hiring manager", "i hope this email finds you well", "i hope this finds you well",
    "please find attached", "passionate about leveraging",
]


def lint_draft(body: str, max_words: int = 120) -> list[str]:
    """Problems with a cold email body; [] means it passes the guide's checklist."""
    problems = []
    words = re.findall(r"[\w'’.-]+", body or "")
    if len(words) > max_words:
        problems.append(f"too long: {len(words)} words (max {max_words})")
    low = (body or "").lower()
    for p in BANNED_PHRASES:
        if p in low:
            problems.append(f"generic phrase: '{p}'")
    if re.search(r"<[^>@\n]{1,40}>|\{\{.*?\}\}|\[(?:name|company|link|project)[^\]]*\]", body or "", re.I):
        problems.append("unfilled placeholder")
    links = re.findall(r"https?://\S+|\b[\w-]+\.(?:com|de|io|dev|app|ai|org|net|me)/\S*", body or "")
    if not links:
        problems.append("no project link")
    asks = [s for s in re.split(r"(?<=[.!?])\s+", body or "") if s.strip().endswith("?")]
    if len(asks) == 0:
        problems.append("no clear ask (end the ask with '?')")
    elif len(asks) > 2:
        problems.append(f"{len(asks)} questions: keep one clear ask")
    return problems
