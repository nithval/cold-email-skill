"""Free job sources and contact pages. Standard library only.

Every job is a dict with: source, id, title, company, location, url,
posted (ISO date or ""), text (plain description), company_site (or ""),
emails (list of {email, source_url, evidence}).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from coldmail import UTC, extract_emails, html_to_text, parse_impressum

UA = "Mozilla/5.0 (compatible; cold-email-skill/1.0; personal job search, low volume)"
TIMEOUT = 20


def http_get(url: str, headers: dict | None = None, timeout: int = TIMEOUT) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en,de;q=0.8", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(25_000_000)
        charset = r.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def get_json(url: str, headers: dict | None = None):
    return json.loads(http_get(url, headers))


def _iso(ts) -> str:
    if ts in (None, ""):
        return ""
    if isinstance(ts, (int, float)):
        if ts > 1e12:
            ts /= 1000
        return dt.datetime.fromtimestamp(ts, UTC).date().isoformat()
    return str(ts)[:10]


def _emails_from(text: str, url: str) -> list[dict]:
    out = []
    for e in extract_emails(text):
        i = text.lower().find(e.split("@")[0])
        ev = re.sub(r"\s+", " ", text[max(0, i - 60): i + 80]).strip() if i >= 0 else ""
        out.append({"email": e, "source_url": url, "evidence": ev})
    return out


CITY_ALIASES = {"munich": "münchen", "cologne": "köln", "nuremberg": "nürnberg", "frankfurt": "frankfurt",
                "düsseldorf": "dusseldorf", "hanover": "hannover"}


def _location_ok(loc: str, cities: list[str]) -> bool:
    if not cities:
        return True
    loc = (loc or "").lower()
    wanted = [c.lower() for c in cities]
    for c in wanted:
        if c != "remote" and (c in loc or CITY_ALIASES.get(c, c) in loc):
            return True
    return "remote" in wanted and "remote" in loc


# ---------------------------------------------------------------- Arbeitnow

def arbeitnow(cities: list[str], pages: int = 3) -> list[dict]:
    """https://www.arbeitnow.com/api/job-board-api (free, no key; Germany-focused)."""
    jobs = []
    for page in range(1, pages + 1):
        data = get_json(f"https://www.arbeitnow.com/api/job-board-api?page={page}")
        for j in data.get("data", []):
            loc = j.get("location", "") + (" remote" if j.get("remote") else "")
            if not _location_ok(loc, cities):
                continue
            text = html_to_text(j.get("description", ""))
            jobs.append({
                "source": "arbeitnow", "id": j.get("slug"), "title": j.get("title", ""),
                "company": j.get("company_name", ""), "location": j.get("location", ""),
                "url": j.get("url", ""), "posted": _iso(j.get("created_at")), "text": text,
                "company_site": "", "emails": _emails_from(text, j.get("url", "")),
            })
        if not data.get("links", {}).get("next"):
            break
    return jobs


# ---------------------------------------------------------------- Bundesagentur für Arbeit

BA_KEY = {"X-API-Key": "jobboerse-jobsuche"}  # public key used by the BA's own web app


def bundesagentur(roles: list[str], cities: list[str], days: int = 30, size: int = 25, details: int = 15) -> list[dict]:
    """BA Jobsuche API search + the public job page's embedded JSON for the full text."""
    jobs, seen = [], set()
    for role in roles:
        for city in cities or [""]:
            q = urllib.parse.urlencode({"was": role, "wo": city, "size": size, "veroeffentlichtseit": days, "angebotsart": 1})
            try:
                data = get_json(f"https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs?{q}", BA_KEY)
            except urllib.error.HTTPError:
                continue
            for j in data.get("ergebnisliste") or data.get("stellenangebote") or []:
                ref = j.get("referenznummer") or j.get("refnr")
                if not ref or ref in seen:
                    continue
                seen.add(ref)
                loc = ((j.get("stellenlokationen") or [{}])[0].get("adresse") or {}).get("ort", "") if j.get("stellenlokationen") else (j.get("arbeitsort") or {}).get("ort", "")
                jobs.append({
                    "source": "bundesagentur", "id": ref, "title": j.get("stellenangebotsTitel") or j.get("titel", ""),
                    "company": j.get("firma") or j.get("arbeitgeber", ""), "location": loc,
                    "url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}",
                    "posted": j.get("datumErsteVeroeffentlichung") or j.get("aktuelleVeroeffentlichungsdatum", ""),
                    "text": "", "company_site": "", "emails": [], "external_url": j.get("externeURL", ""),
                })
    for job in jobs[:details]:
        enrich_bundesagentur(job)
    return jobs


def enrich_bundesagentur(job: dict) -> dict:
    """Full description, employer site and any contact email from the public BA job page."""
    try:
        page = http_get(job["url"])
    except Exception:
        return job
    m = re.search(r'<script id="ng-state" type="application/json">(.*?)</script>', page, re.S)
    if not m:
        return job
    try:
        state = json.loads(m.group(1))
    except json.JSONDecodeError:
        return job
    d = state.get("jobdetail") or {}
    text = d.get("stellenangebotsBeschreibung", "") or ""
    contact = json.dumps({k: v for k, v in d.items() if re.search(r"kontakt|ansprech|bewerbung", k, re.I)}, ensure_ascii=False)
    job["text"] = text
    # allianzpartnerUrl is usually a partner job board; keep it only when it is clearly the employer's own domain
    site = d.get("allianzpartnerUrl") or ""
    token = re.sub(r"[^a-z0-9]", "", (job.get("company") or "").lower().split(" ")[0])
    if site and len(token) >= 3 and token in site.lower() and is_company_site(site):
        job["company_site"] = site if site.startswith("http") else "https://" + site
    job["emails"] = _emails_from(text + "\n" + contact, job["url"])
    return job


# ---------------------------------------------------------------- Hacker News "Who is hiring?"

def hn_who_is_hiring(cities: list[str], months: int = 1) -> list[dict]:
    stories = get_json("https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&query=who%20is%20hiring&hitsPerPage=6")
    hits = [h for h in stories.get("hits", []) if h.get("title", "").startswith("Ask HN: Who is hiring?")][:months]
    names = [c for c in cities if c.lower() != "remote"]
    names += [CITY_ALIASES[c.lower()] for c in names if c.lower() in CITY_ALIASES]
    city_rx = re.compile("|".join(re.escape(c) for c in names + ["Germany", "Deutschland"]), re.I)
    jobs = []
    for h in hits:
        item = get_json(f"https://hn.algolia.com/api/v1/items/{h['objectID']}")
        for c in item.get("children", []):
            raw = c.get("text") or ""
            text = html_to_text(raw)
            head = text.split("\n", 1)[0]
            if not city_rx.search(head):  # the location lives in the "Company | Role | Place" header line
                continue
            parts = [p.strip() for p in head.split("|")]
            url = f"https://news.ycombinator.com/item?id={c['id']}"
            site = re.search(r"https?://[^\s|)]+", text)
            jobs.append({
                "source": "hn", "id": str(c["id"]), "title": parts[1] if len(parts) > 1 else head[:80],
                "company": parts[0][:60], "location": " | ".join(parts[2:4]), "url": url,
                "posted": _iso(c.get("created_at_i")), "text": text,
                "company_site": site.group(0).rstrip(".,") if site else "", "emails": _emails_from(text, url),
            })
    return jobs


# ---------------------------------------------------------------- public ATS feeds

def ats_jobs(kind: str, slug: str, cities: list[str]) -> list[dict]:
    """Greenhouse / Lever / Ashby / Personio public job feeds for one company."""
    out = []
    if kind == "greenhouse":
        data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
        for j in data.get("jobs", []):
            out.append((j["id"], j["title"], (j.get("location") or {}).get("name", ""), j.get("absolute_url", ""),
                        _iso(j.get("first_published") or j.get("updated_at")), html_to_text(j.get("content", "")), j.get("company_name") or slug))
    elif kind == "lever":
        for j in get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json"):
            cat = j.get("categories") or {}
            out.append((j["id"], j["text"], cat.get("location", ""), j.get("hostedUrl", ""),
                        _iso(j.get("createdAt")), j.get("descriptionPlain", "") + "\n" + " ".join(
                            html_to_text(x.get("content", "")) for x in j.get("lists", [])), slug))
    elif kind == "ashby":
        data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        for j in data.get("jobs", []):
            locs = j.get("location", "") + " " + " ".join(s.get("location", "") for s in j.get("secondaryLocations") or [])
            out.append((j["id"], j["title"], locs.strip(), j.get("jobUrl", ""), _iso(j.get("publishedAt")),
                        j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", "")), slug))
    elif kind == "personio":
        xml = http_get(f"https://{slug}.jobs.personio.de/xml?language=en")
        for pos in re.findall(r"<position>(.*?)</position>", xml, re.S):
            g = lambda tag: (re.search(rf"<{tag}>(.*?)</{tag}>", pos, re.S) or [None, ""])[1]
            pid = g("id")
            out.append((pid, html_to_text(g("name")), html_to_text(g("office")), f"https://{slug}.jobs.personio.de/job/{pid}",
                        _iso(g("createdAt")), html_to_text(re.sub(r"<!\[CDATA\[|\]\]>", "", pos)), slug))
    else:
        raise ValueError(f"unknown ATS kind {kind}")
    jobs = []
    for jid, title, loc, url, posted, text, company in out:
        if not _location_ok(loc, cities):
            continue
        jobs.append({"source": kind, "id": str(jid), "title": title, "company": company, "location": loc,
                     "url": url, "posted": posted, "text": text, "company_site": "",
                     "emails": _emails_from(text, url)})
    return jobs


# ---------------------------------------------------------------- recruiting agencies

_AGENCY_NAME = re.compile(r"personal(?:service|dienst|beratung|vermittlung)?\b|recruit|talent|staffing|headhunt|consult(?:ing|ants)?\b|zeitarbeit|arbeitnehmerüberlassung|hays|randstad|adecco|manpower|gulp|amadeus fire|etengo", re.I)
_AGENCY_TEXT = re.compile(r"unser(?:em|en)? (?:Kunde|Kunden|Mandant)|for our client|on behalf of our client|im Auftrag unseres|Arbeitnehmerüberlassung", re.I)


def is_agency(job: dict) -> bool:
    """Recruiting agencies post for someone else: the founder you want to reach is not behind the ad."""
    return bool(_AGENCY_NAME.search(job.get("company", "")) or _AGENCY_TEXT.search(job.get("text", "")[:4000]))


# ---------------------------------------------------------------- company contact pages

CONTACT_PATHS = ["impressum", "imprint", "legal-notice", "de/impressum", "en/imprint", "legal", "kontakt", "contact",
                 "team", "about"]

# Job boards and ATS hosts are never "the company's site".
NOT_COMPANY_SITES = re.compile(
    r"(^|\.)(arbeitsagentur|arbeitnow|greenhouse|lever|ashbyhq|personio|linkedin|ycombinator|stepstone|indeed|"
    r"xing|glassdoor|join|softgarden|smartrecruiters|workday|myworkdayjobs|recruitee|teamtailor|jobvite|"
    r"successfactors|yourfirm|jobware|monster|kununu)\.", re.I)


def is_company_site(url: str) -> bool:
    host = urllib.parse.urlparse(url if "://" in url else "https://" + url).netloc
    return bool(host) and not NOT_COMPANY_SITES.search(host + ".")


def company_contacts(site: str, max_pages: int = 5, delay: float = 0.3) -> dict:
    """Emails + managing directors from a company's Impressum / contact / team pages.

    Returns {"site", "managing_directors": [{name, source_url}], "emails": [{email, source_url, evidence}],
    "pages_checked": [...]}. Only pages that answer 200 are read. Nothing is guessed.
    Stops once an Impressum-style page gave both a managing director and an email.
    """
    p = urllib.parse.urlparse(site if "://" in site else "https://" + site)
    base = f"{p.scheme or 'https'}://{p.netloc}"
    result = {"site": base, "managing_directors": [], "emails": [], "pages_checked": []}
    if not is_company_site(base):
        result["error"] = "job board / ATS host, not the company's own site"
        return result
    host = p.netloc.removeprefix("www.")
    seen_emails: set = set()
    linked = []
    try:  # follow the site's own Impressum/contact links first
        home = http_get(base + "/", timeout=10)
        for href in re.findall(r'href=["\']([^"\'#]+)["\']', home):
            if re.search(r"impressum|imprint|legal-notice|kontakt|contact|team", href, re.I) and "mailto:" not in href:
                linked.append(urllib.parse.urljoin(base + "/", href))
        _collect(result, seen_emails, base + "/", home)
    except Exception:
        pass
    linked.sort(key=lambda u: 0 if re.search(r"impressum|imprint|legal", u, re.I) else 1)
    checked = 0
    for url in dict.fromkeys(linked + [f"{base}/{path}" for path in CONTACT_PATHS]):
        if checked >= max_pages:
            break
        if urllib.parse.urlparse(url).netloc.removeprefix("www.") != host:
            continue
        try:
            page = http_get(url, timeout=10)
        except Exception:
            continue
        checked += 1
        _collect(result, seen_emails, url, page)
        if result["managing_directors"] and result["emails"]:
            break
        time.sleep(delay)
    return result


def _collect(result: dict, seen: set, url: str, page: str) -> None:
    result["pages_checked"].append(url)
    text = html_to_text(page)
    imp = parse_impressum(text)
    for name in imp.managing_directors:
        if name not in [m["name"] for m in result["managing_directors"]]:
            result["managing_directors"].append({"name": name, "source_url": url})
    for e in _emails_from(text, url):
        if e["email"] not in seen:
            seen.add(e["email"])
            result["emails"].append(e)

