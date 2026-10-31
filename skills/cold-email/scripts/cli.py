#!/usr/bin/env python3
"""/cold-email command line. Standard library only.

  cli.py profile init --cv CV.pdf          extract CV text + sections
  cli.py profile set --roles ... --cities ...
  cli.py profile show
  cli.py find [--sources arbeitnow,bundesagentur,hn,ats] [--min-score 0.3]
  cli.py linkedin --url URL --title T --snippet S [--company C]   add one search hit
  cli.py contacts --site https://company.de [--job ID]           Impressum/contact emails
  cli.py shortlist [--limit 10]                                  ranked jobs with a sourced contact
  cli.py lint [FILE|-]                                           check a draft against the guide
  cli.py track add|list|followups|set ...                        the tracker CSV

Data lives in $COLD_EMAIL_HOME (default ~/.cold-email), never in the repo.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coldmail as cm  # noqa: E402
import sources as src  # noqa: E402

HOME = Path(os.environ.get("COLD_EMAIL_HOME", Path.home() / ".cold-email"))
PROFILE = HOME / "profile.json"
CV_TXT = HOME / "cv.txt"
TRACKER = HOME / "tracker.csv"
TRACKER_COLS = ["date", "company", "person", "email", "email_source_url", "job_title", "job_url", "score",
                "status", "gmail_draft_id", "followup_due", "notes"]


def today() -> str:
    return dt.date.today().isoformat()


def run_dir() -> Path:
    d = HOME / "runs" / today()
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_profile() -> dict:
    if not PROFILE.exists():
        sys.exit("No profile yet. Run: cli.py profile init --cv <your CV>, then cli.py profile set ...")
    return json.loads(PROFILE.read_text())


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------- profile

def cv_text(path: Path) -> str:
    suf = path.suffix.lower()
    if suf == ".pdf":
        if shutil.which("pdftotext"):
            return subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, check=True).stdout
        sys.exit("pdftotext not found. Ask Claude to read the PDF and save the text with: cli.py profile init --cv cv.txt")
    if suf == ".docx":
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        xml = re.sub(r"</w:p>", "\n", xml)
        return cm.html.unescape(re.sub(r"<[^>]+>", "", xml))
    return path.read_text(errors="replace")


def cmd_profile(a) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    if a.action == "init":
        text = cv_text(Path(a.cv).expanduser())
        CV_TXT.write_text(text)
        secs = cm.split_cv_sections(text)
        weights = cm.cv_terms(secs)
        prof = json.loads(PROFILE.read_text()) if PROFILE.exists() else {}
        prof.update({"cv_file": str(Path(a.cv).expanduser()), "cv_terms": weights,
                     "cv_sections_found": [k for k, v in secs.items() if v.strip()], "updated": today()})
        save_json(PROFILE, prof)
        top = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))[:20]
        print(json.dumps({"sections": prof["cv_sections_found"], "top_terms": top, "profile": str(PROFILE)}, indent=2))
    elif a.action == "set":
        prof = json.loads(PROFILE.read_text()) if PROFILE.exists() else {}
        for key in ("roles", "cities", "seniority", "watch"):
            val = getattr(a, key)
            if val is not None:
                prof[key] = [v.strip() for v in val.split(",") if v.strip()]
        for key in ("sender_name", "project_line", "project_link", "links", "min_score", "max_age_days", "signature"):
            val = getattr(a, key)
            if val is not None:
                prof[key] = float(val) if key in ("min_score", "max_age_days") else val
        prof["updated"] = today()
        save_json(PROFILE, prof)
        print(json.dumps({k: v for k, v in prof.items() if k != "cv_terms"}, indent=2, ensure_ascii=False))
    else:
        prof = load_profile()
        print(json.dumps({k: v for k, v in prof.items() if k != "cv_terms"} | {"cv_terms_count": len(prof.get("cv_terms", {}))},
                         indent=2, ensure_ascii=False))


# ---------------------------------------------------------------- find

def _fresh(job: dict, max_age: float) -> bool:
    if not job.get("posted"):
        return True
    try:
        d = dt.date.fromisoformat(job["posted"][:10])
    except ValueError:
        return True
    return (dt.date.today() - d).days <= max_age


def _evaluate(job: dict, prof: dict) -> dict:
    m = cm.score_posting(prof.get("cv_terms", {}), job.get("title", "") + "\n" + job.get("text", ""))
    job["score"], job["matched"], job["missing"] = m.score, m.matched, m.missing
    job["title_match"] = cm.title_matches(job.get("title", ""), prof.get("roles", []))
    job["seniority_ok"] = cm.seniority_ok(job.get("title", ""), prof.get("seniority", []))
    job["agency"] = src.is_agency(job)
    return job


def jobs_path() -> Path:
    return run_dir() / "jobs.json"


def load_jobs() -> list[dict]:
    p = jobs_path()
    return json.loads(p.read_text()) if p.exists() else []


def cmd_find(a) -> None:
    prof = load_profile()
    roles, cities = prof.get("roles", []), prof.get("cities", [])
    max_age = prof.get("max_age_days", 30)
    wanted = set(a.sources.split(","))
    jobs, report = [], {}

    def run(name, fn):
        try:
            got = fn()
            report[name] = f"ok, {len(got)} jobs"
            jobs.extend(got)
        except Exception as e:  # one dead source must not stop the run
            report[name] = f"failed: {type(e).__name__}: {e}"[:160]

    if "arbeitnow" in wanted:
        run("arbeitnow", lambda: src.arbeitnow(cities))
    if "bundesagentur" in wanted:
        run("bundesagentur", lambda: src.bundesagentur(roles, [c for c in cities if c.lower() != "remote"], days=int(max_age)))
    if "hn" in wanted:
        run("hn", lambda: src.hn_who_is_hiring(cities))
    if "ats" in wanted:
        for w in prof.get("watch", []):  # "greenhouse:celonis=celonis.com", "ashby:moss", ...
            kind, _, rest = w.partition(":")
            slug, _, site = rest.partition("=")

            def fetch(kind=kind, slug=slug, site=site):
                got = src.ats_jobs(kind, slug, cities)
                for j in got:
                    j["company_site"] = ("https://" + site) if site and "://" not in site else site
                return got
            run(f"{kind}:{slug}", fetch)

    merged = [j for j in load_jobs() if j.get("source") == "linkedin"]  # LinkedIn hits added via `linkedin`
    for j in jobs:
        if not _fresh(j, max_age):
            continue
        _evaluate(j, prof)
        merged.append(j)
    # BA ads that made the shortlist get their full page now (contact + text) if not done yet
    for j in merged:
        if j["source"] == "bundesagentur" and not j.get("text") and j["title_match"] and j["seniority_ok"]:
            src.enrich_bundesagentur(j)
            _evaluate(j, prof)
    save_json(jobs_path(), merged)
    good = [j for j in merged if j["title_match"] and j["seniority_ok"] and j["score"] >= a.min_score]
    print(json.dumps({"sources": report, "jobs_total": len(merged), "good_matches": len(good),
                      "with_email_in_ad": sum(1 for j in good if j.get("emails")), "saved": str(jobs_path())}, indent=2))


def cmd_linkedin(a) -> None:
    """Add one public LinkedIn post from a web-search result (URL + snippet only; LinkedIn is never opened)."""
    prof = load_profile()
    age = cm.post_age_days(a.url, a.snippet)
    max_age = prof.get("max_age_days", 30)
    if age is None:
        print(json.dumps({"added": False, "reason": "post date unknown (no activity id, no 'N days ago' in snippet)"}))
        return
    if age > max_age:
        print(json.dumps({"added": False, "reason": f"too old: {age:.0f} days"}))
        return
    posted = (dt.datetime.now(cm.UTC) - dt.timedelta(days=age)).date().isoformat()
    m = re.search(r"activity-(\d+)", a.url)
    job = {"source": "linkedin", "id": m.group(1) if m else a.url, "title": a.title, "company": a.company or "",
           "location": "", "url": a.url, "posted": posted, "text": a.snippet, "company_site": a.site or "",
           "emails": src._emails_from(a.snippet, a.url), "score_basis": "search snippet only"}
    _evaluate(job, prof)
    jobs = [j for j in load_jobs() if not (j["source"] == "linkedin" and j["id"] == job["id"])] + [job]
    save_json(jobs_path(), jobs)
    print(json.dumps({"added": True, "posted": posted, "age_days": round(age, 1), "score": job["score"],
                      "title_match": job["title_match"], "emails_found": len(job["emails"])}))


def cmd_contacts(a) -> None:
    res = src.company_contacts(a.site, max_pages=a.max_pages)
    if a.job:
        jobs = load_jobs()
        for j in jobs:
            if j["id"] == a.job:
                j["company_site"] = res["site"]
                j["contacts"] = res
        save_json(jobs_path(), jobs)
    print(json.dumps(res, indent=2, ensure_ascii=False))


def best_contact(job: dict) -> dict | None:
    """Best sourced email for a job: person from the ad > jobs@ in the ad > Impressum/contact page emails."""
    pool = [dict(e, origin="job ad") for e in job.get("emails", [])]
    pool += [dict(e, origin="company page") for e in (job.get("contacts") or {}).get("emails", [])]
    pool = [e for e in pool if e.get("source_url")]
    if not pool:
        return None
    pool.sort(key=lambda e: (cm.KIND_RANK[cm.email_kind(e["email"])], e["origin"] != "job ad"))
    best = dict(pool[0], kind=cm.email_kind(pool[0]["email"]))
    mds = (job.get("contacts") or {}).get("managing_directors", [])
    if mds:
        best["managing_directors"] = mds
    return best


def already_tracked() -> set[str]:
    if not TRACKER.exists():
        return set()
    rows = _read_tracker()
    return {r["email"].lower() for r in rows} | {r["job_url"] for r in rows if r["job_url"]}


def cmd_shortlist(a) -> None:
    prof = load_profile()
    min_score = a.min_score if a.min_score is not None else prof.get("min_score", 0.3)
    tracked = already_tracked()
    jobs = load_jobs()
    resolved = 0
    seen_keys: set = set()
    rows = []
    for j in sorted(jobs, key=lambda j: -j.get("score", 0)):
        if not (j.get("title_match") and j.get("seniority_ok") and j.get("score", 0) >= min_score):
            continue
        if j.get("agency") and not a.include_agencies:
            continue
        c = best_contact(j)
        key = (re.sub(r"\W+", "", j["company"].lower())[:12], re.sub(r"\W+", "", j["title"].lower())[:10])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        if not c and j.get("company_site") and src.is_company_site(j["company_site"]) and "contacts" not in j and resolved < a.resolve:
            j["contacts"] = src.company_contacts(j["company_site"])  # Impressum / contact / team pages
            resolved += 1
            c = best_contact(j)
        if a.need_contact and not c:
            continue
        if c and (c["email"] in tracked or j["url"] in tracked):
            continue
        rows.append({"id": j["id"], "source": j["source"], "title": j["title"], "company": j["company"],
                     "location": j.get("location", ""), "posted": j.get("posted", ""), "score": j["score"],
                     "matched": j.get("matched", [])[:8], "missing": j.get("missing", [])[:5], "url": j["url"],
                     "company_site": j.get("company_site", ""), "contact": c or "no contact found"})
        if len(rows) >= a.limit:
            break
    if resolved:
        save_json(jobs_path(), jobs)
    print(json.dumps(rows, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------- lint + tracker

def cmd_lint(a) -> None:
    body = sys.stdin.read() if a.file in (None, "-") else Path(a.file).read_text()
    problems = cm.lint_draft(body)
    words = len(re.findall(r"[\w'’.-]+", body))
    print(json.dumps({"ok": not problems, "words": words, "problems": problems}))
    sys.exit(1 if problems else 0)


def _read_tracker() -> list[dict]:
    if not TRACKER.exists():
        return []
    with TRACKER.open() as f:
        return list(csv.DictReader(f))


def _write_tracker(rows: list[dict]) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    with TRACKER.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TRACKER_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in TRACKER_COLS})


def cmd_track(a) -> None:
    rows = _read_tracker()
    if a.action == "add":
        if not a.email_source_url:
            sys.exit("Every email needs --email-source-url (where the address was found).")
        due = (dt.date.today() + dt.timedelta(days=a.followup_days)).isoformat()
        rows.append({"date": today(), "company": a.company, "person": a.person or "", "email": a.email.lower(),
                     "email_source_url": a.email_source_url, "job_title": a.job_title or "", "job_url": a.job_url or "",
                     "score": a.score or "", "status": a.status, "gmail_draft_id": a.draft_id or "",
                     "followup_due": due, "notes": a.notes or ""})
        _write_tracker(rows)
        print(json.dumps({"tracked": a.email.lower(), "status": a.status, "followup_due": due}))
    elif a.action == "set":
        n = 0
        for r in rows:
            if r["email"] == a.email.lower():
                r["status"] = a.status
                if a.notes:
                    r["notes"] = (r["notes"] + "; " if r["notes"] else "") + a.notes
                n += 1
        _write_tracker(rows)
        print(json.dumps({"updated": n}))
    elif a.action == "followups":
        due = [r for r in rows if r["status"] == "sent" and r["followup_due"] and r["followup_due"] <= today()]
        print(json.dumps(due, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(rows, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------- main

def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("profile")
    pp.add_argument("action", choices=["init", "set", "show"])
    pp.add_argument("--cv")
    for k in ("roles", "cities", "seniority", "watch", "sender-name", "project-line", "project-link", "links",
              "min-score", "max-age-days", "signature"):
        pp.add_argument(f"--{k}")
    pp.set_defaults(fn=cmd_profile)

    pf = sub.add_parser("find")
    pf.add_argument("--sources", default="arbeitnow,bundesagentur,hn,ats")
    pf.add_argument("--min-score", type=float, default=0.3)
    pf.set_defaults(fn=cmd_find)

    pl = sub.add_parser("linkedin")
    pl.add_argument("--url", required=True)
    pl.add_argument("--title", default="")
    pl.add_argument("--snippet", default="")
    pl.add_argument("--company")
    pl.add_argument("--site")
    pl.set_defaults(fn=cmd_linkedin)

    pc = sub.add_parser("contacts")
    pc.add_argument("--site", required=True)
    pc.add_argument("--job")
    pc.add_argument("--max-pages", type=int, default=6)
    pc.set_defaults(fn=cmd_contacts)

    ps = sub.add_parser("shortlist")
    ps.add_argument("--limit", type=int, default=10)
    ps.add_argument("--min-score", type=float)
    ps.add_argument("--need-contact", action="store_true")
    ps.add_argument("--include-agencies", action="store_true")
    ps.add_argument("--resolve", type=int, default=10, help="check Impressum/contact pages for up to N jobs without an email")
    ps.set_defaults(fn=cmd_shortlist)

    pli = sub.add_parser("lint")
    pli.add_argument("file", nargs="?")
    pli.set_defaults(fn=cmd_lint)

    pt = sub.add_parser("track")
    pt.add_argument("action", choices=["add", "set", "list", "followups"])
    pt.add_argument("--email", default="")
    pt.add_argument("--email-source-url")
    pt.add_argument("--company", default="")
    pt.add_argument("--person")
    pt.add_argument("--job-title")
    pt.add_argument("--job-url")
    pt.add_argument("--score")
    pt.add_argument("--status", default="drafted", choices=["drafted", "sent", "replied", "followup_drafted", "skipped", "closed"])
    pt.add_argument("--draft-id")
    pt.add_argument("--followup-days", type=int, default=5)
    pt.add_argument("--notes")
    pt.set_defaults(fn=cmd_track)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
