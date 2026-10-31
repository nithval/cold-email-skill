#!/usr/bin/env python3
"""Which parts of /cold-email work on this machine? Prints PASS / WARN / FAIL per piece.

  python3 selftest.py            all checks (needs internet for the sources)
  python3 selftest.py --offline  parsers + local setup only

Gmail cannot be checked from a script: ask Claude "check my Gmail connector for /cold-email".
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

results: list[tuple[str, str, str]] = []


def check(name: str, fn, warn_only: bool = False) -> None:
    try:
        detail = fn() or ""
        results.append(("PASS", name, str(detail)))
    except Exception as e:  # report and keep going
        results.append(("WARN" if warn_only else "FAIL", name, f"{type(e).__name__}: {e}"[:140]))


def t_python():
    assert sys.version_info >= (3, 9), sys.version
    return sys.version.split()[0]


def t_parsers():
    import coldmail as cm
    assert cm.linkedin_post_date("https://www.linkedin.com/posts/x-activity-7519727902532358144-UndX").date().isoformat() == "2026-10-24"
    assert cm.extract_emails("jobs [at] acme [dot] de, noreply@acme.de") == ["jobs@acme.de"]
    imp = cm.parse_impressum("Acme GmbH\nGeschäftsführer: Anna Schmidt\nE-Mail: info@acme.de")
    assert imp.managing_directors == ["Anna Schmidt"] and imp.emails == ["info@acme.de"]
    assert cm.lint_draft("Hi Anna,\nSee https://x.io/demo.\nWould you be open to a 15-minute chat?") == []
    return "date decode, emails, Impressum, draft lint"


def t_pdftotext():
    if not shutil.which("pdftotext"):
        raise RuntimeError("not installed (PDF CVs: Claude can read the PDF instead; or brew/apt install poppler)")
    return shutil.which("pdftotext")


def t_home():
    home = Path(os.environ.get("COLD_EMAIL_HOME", Path.home() / ".cold-email"))
    home.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=home):
        pass
    prof = home / "profile.json"
    return f"{home} (profile: {'yes' if prof.exists() else 'not yet, run profile init'})"


def t_arbeitnow():
    import sources
    d = sources.get_json("https://www.arbeitnow.com/api/job-board-api")
    assert d.get("data"), "empty"
    return f"{len(d['data'])} jobs on page 1"


def t_bundesagentur():
    import sources
    d = sources.get_json("https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs?was=Softwareentwickler&wo=Berlin&size=1",
                         sources.BA_KEY)
    n = d.get("maxErgebnisse")
    assert d.get("ergebnisliste"), "no results"
    return f"{n} Softwareentwickler jobs in Berlin"


def t_ba_detail():
    import sources
    d = sources.get_json("https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs?was=Softwareentwickler&wo=Berlin&size=1",
                         sources.BA_KEY)
    ref = d["ergebnisliste"][0]["referenznummer"]
    job = sources.enrich_bundesagentur({"url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}", "company": ""})
    assert job.get("text"), "job page had no description"
    return f"full ad text read ({len(job['text'])} chars)"


def t_hn():
    import sources
    d = sources.get_json("https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&query=who%20is%20hiring&hitsPerPage=3")
    titles = [h["title"] for h in d["hits"] if h["title"].startswith("Ask HN: Who is hiring?")]
    assert titles, "no thread found"
    return titles[0]


def t_ats():
    import sources
    out = []
    for kind, slug in (("greenhouse", "getyourguide"), ("ashby", "moss")):
        out.append(f"{kind}:{slug} {len(sources.ats_jobs(kind, slug, []))}")
    return ", ".join(out)


def t_contacts():
    import sources
    page = sources.http_get("https://www.arbeitnow.com/", timeout=15)
    assert "<html" in page.lower()
    return "company pages reachable (Impressum crawl uses the same client)"


def main() -> None:
    offline = "--offline" in sys.argv
    check("python >= 3.9", t_python)
    check("parsers", t_parsers)
    check("data folder writable", t_home)
    check("pdftotext (PDF CVs)", t_pdftotext, warn_only=True)
    if not offline:
        check("Arbeitnow API", t_arbeitnow)
        check("Bundesagentur Jobsuche API", t_bundesagentur)
        check("Bundesagentur job page (full ad)", t_ba_detail, warn_only=True)
        check("Hacker News Who is hiring", t_hn)
        check("Greenhouse / Ashby feeds", t_ats)
        check("web pages (Impressum crawl)", t_contacts)
    results.append(("INFO", "LinkedIn posts", "found by Claude's web search tool at run time (no script, no login)"))
    results.append(("INFO", "Gmail drafts", "needs the Gmail connector in Claude; ask Claude to check it"))
    w = max(len(n) for _, n, _ in results)
    for status, name, detail in results:
        print(f"{status:4}  {name:<{w}}  {detail}")
    fails = sum(1 for s, _, _ in results if s == "FAIL")
    print(f"\n{'All required checks passed.' if not fails else f'{fails} required check(s) failed.'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
