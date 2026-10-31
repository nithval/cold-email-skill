"""Parser evals. Run: python3 -m unittest discover -s tests -v  (no network)."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "cold-email" / "scripts"))
import coldmail as cm  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
NOW = dt.datetime(2026, 10, 31, 20, 0, tzinfo=cm.UTC)


class LinkedInDate(unittest.TestCase):
    # Real public post URLs from a 31 Oct 2026 web search; the snippet of the first said "8 days ago".
    def test_activity_ids_decode_to_real_dates(self):
        cases = {
            "https://www.linkedin.com/posts/dakshintalks_studyingermany-internationalstudents-werkstudent-activity-7519727902532358144-UndX": "2026-10-24",
            "https://www.linkedin.com/posts/jobs-without-german_jobsingermany-werkstudent-studentjobs-activity-7514175863353921536-WBVh": "2026-10-09",
            "https://www.linkedin.com/posts/edunirvana_how-to-get-part-time-job-in-germany-in-2026-activity-7425046762442129409-DqOd": "2026-02-05",
        }
        for url, day in cases.items():
            self.assertEqual(cm.linkedin_post_date(url).date().isoformat(), day, url)

    def test_snippet_age_matches_decoded_age(self):
        url = "https://www.linkedin.com/posts/dakshintalks_x-activity-7519727902532358144-UndX"
        decoded = cm.post_age_days(url, now=NOW)
        self.assertAlmostEqual(decoded, 7.3, delta=1.0)  # snippet said "8 days ago"

    def test_ugcpost_and_no_id(self):
        self.assertIsNotNone(cm.linkedin_post_date("https://www.linkedin.com/feed/update/urn:li:ugcPost:7519727902532358144/"))
        self.assertIsNone(cm.linkedin_post_date("https://www.linkedin.com/in/someone/"))
        self.assertIsNone(cm.linkedin_post_date("https://www.linkedin.com/posts/x-activity-12345-abc"))

    def test_relative_age(self):
        self.assertEqual(cm.relative_age_days("Jane · 8 days ago · hiring"), 8)
        self.assertEqual(cm.relative_age_days("vor 3 Tagen"), 3)
        self.assertEqual(cm.relative_age_days("Max Muster 2w • Edited"), 14)
        self.assertEqual(cm.relative_age_days("3mo · We are hiring"), 90)
        self.assertIsNone(cm.relative_age_days("We do 3D printing and 24h support"))
        # profile URL without id falls back to the snippet
        self.assertEqual(cm.post_age_days("https://www.linkedin.com/in/x/", "posted 5 days ago"), 5)


class Emails(unittest.TestCase):
    def test_plain_and_obfuscated(self):
        text = ("Send your CV to jobs [at] acme-robotics [dot] de or to Anna.Schmidt(at)acme-robotics.de. "
                "Questions: hello&#64;acme.io, <a href='mailto:cto@acme.io?subject=hi'>mail</a> "
                "or kontakt [ät] acme [punkt] de")
        self.assertEqual(cm.extract_emails(text), [
            "jobs@acme-robotics.de", "anna.schmidt@acme-robotics.de", "hello@acme.io", "cto@acme.io", "kontakt@acme.de"])

    def test_blocked_and_noise(self):
        text = ("noreply@acme.de datenschutz@acme.de privacy@acme.de logo@2x.png sprite@3x.webp "
                "user@example.com a.b@sentry.io meet me at 5 dot com")
        self.assertEqual(cm.extract_emails(text), [])

    def test_kinds(self):
        self.assertEqual(cm.email_kind("anna.schmidt@acme.de"), "person")
        self.assertEqual(cm.email_kind("jobs@acme.de"), "jobs")
        self.assertEqual(cm.email_kind("karriere@acme.de"), "jobs")
        self.assertEqual(cm.email_kind("info@acme.de"), "generic")

    def test_real_hn_comment_shape(self):
        text = (FIX / "hn_comment.txt").read_text()
        self.assertEqual(cm.extract_emails(text), ["hiring@quietstack.dev"])


class ImpressumParsing(unittest.TestCase):
    def test_german_impressum_html(self):
        imp = cm.parse_impressum((FIX / "impressum_de.html").read_text())
        self.assertEqual(imp.company, "Beispiel Robotics GmbH")
        self.assertEqual(imp.managing_directors, ["Dr. Anna Schmidt", "Jonas Weber"])
        self.assertEqual(imp.emails, ["info@beispiel-robotics.de"])  # datenschutz@ is dropped

    def test_english_imprint(self):
        imp = cm.parse_impressum((FIX / "imprint_en.txt").read_text())
        self.assertEqual(imp.company, "Example Labs GmbH")
        self.assertEqual(imp.managing_directors, ["Lena Fischer", "Tom Becker"])
        self.assertEqual(imp.emails, ["hello@examplelabs.ai"])

    def test_vertreten_durch(self):
        imp = cm.parse_impressum("Muster UG (haftungsbeschränkt)\nVertreten durch: Max Mustermann\nTelefon: 030 1234")
        self.assertEqual(imp.managing_directors, ["Max Mustermann"])


class Matching(unittest.TestCase):
    CV = """Jane Doe
EXPERIENCE
Backend Engineer, Acme  2022 - 2025
 - Built Python and FastAPI services on AWS with PostgreSQL
PROJECTS
 - RAG chatbot with LangChain and Docker
SKILLS
Languages: Python, TypeScript, SQL
Tools: Kubernetes, Terraform
"""

    def test_sections_and_weights(self):
        secs = cm.split_cv_sections(self.CV)
        w = cm.cv_terms(secs)
        self.assertEqual(w["python"], 1.0)        # experience
        self.assertEqual(w["langchain"], 0.75)    # projects
        self.assertEqual(w["kubernetes"], 0.5)    # skills only
        self.assertNotIn("java", w)

    def test_score_orders_postings(self):
        w = cm.cv_terms(cm.split_cv_sections(self.CV))
        good = cm.score_posting(w, "We build with Python, FastAPI, PostgreSQL on AWS and Kubernetes.")
        bad = cm.score_posting(w, "Java, Spring Boot, Angular and Oracle for our banking core.")
        self.assertGreater(good.score, 0.6)
        self.assertLess(bad.score, 0.1)
        self.assertIn("fastapi", good.matched)
        self.assertIn("java", bad.missing)

    def test_go_is_case_sensitive(self):
        self.assertFalse(cm.has_term("Ready to go the extra mile?", "go"))
        self.assertTrue(cm.has_term("Services in Go and Rust", "go"))

    def test_title_and_level(self):
        self.assertTrue(cm.title_matches("Senior Backend Engineer (m/w/d)", ["Backend Engineer"]))
        self.assertFalse(cm.title_matches("Sales Manager", ["Backend Engineer"]))
        self.assertTrue(cm.seniority_ok("Werkstudent Software Engineering", ["student"]))
        self.assertFalse(cm.seniority_ok("Senior Software Engineer", ["student", "junior"]))
        self.assertTrue(cm.seniority_ok("Software Engineer", ["mid"]))


class DraftLint(unittest.TestCase):
    GOOD = """Hi Lena,

Your post about moving inference to the edge stuck with me.

I came across your Backend Engineer opening and wanted to reach out directly.
I prefer to let what I build speak louder than a traditional self-introduction:
a Kafka event replayer that cut incident debugging from hours to minutes -> https://github.com/someone/replayer

You run Go and Kafka on Kubernetes, which is exactly my stack.

Would you be open to a 15-minute chat this week?

Best,
Alex"""

    def test_good_draft_passes(self):
        self.assertEqual(cm.lint_draft(self.GOOD), [])

    def test_bad_drafts(self):
        self.assertIn("no project link", cm.lint_draft("Hi, I am writing to express my interest. Any opportunities?")[1:])
        self.assertTrue(any("generic phrase" in p for p in cm.lint_draft("I am writing to express interest. https://x.io Chat?")))
        self.assertTrue(any("placeholder" in p for p in cm.lint_draft("Hi <first name>, see https://x.io. Chat?")))
        self.assertTrue(any("too long" in p for p in cm.lint_draft(("word " * 130) + "https://x.io Chat?")))
        self.assertTrue(any("no clear ask" in p for p in cm.lint_draft("Hi Lena. Here is my thing https://x.io.")))


if __name__ == "__main__":
    unittest.main()
