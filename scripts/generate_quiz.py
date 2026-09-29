#!/usr/bin/env python3
"""
QuizPop daily content pipeline — runs on GitHub Actions (free tier).
Trend discovery -> topic scoring -> quiz generation (Gemini API) ->
writes quiz pages -> updates quizzes.json + sitemap.xml.

Stdlib only. Two-phase: all quizzes are generated and validated BEFORE
anything is written, so a failure never leaves a half-built site.

Env:
  GEMINI_API_KEY   required (GitHub repo secret)
  GEMINI_MODEL     default: gemini-2.0-flash
  QUIZZES_PER_DAY  default: 3
  SITE_DOMAIN      default: https://quizpop.example/
"""
import html
import json
import os
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # repo root (quizpop-site contents)
API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
PER_DAY = int(os.environ.get("QUIZZES_PER_DAY", "3"))
DOMAIN = os.environ.get("SITE_DOMAIN", "https://quizpop.example/").rstrip("/") + "/"

STATIC_PAGES = ["", "personality/", "trivia/", "riddles/", "trending/",
                "search/", "about/", "contact/", "privacy/", "terms/", "disclosure/"]


# ── Gemini REST call (stdlib only) ──────────────────────────────────────────
def gemini(prompt, temperature=0.9):
    if not API_KEY:
        sys.exit("ERROR: GEMINI_API_KEY is not set.")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{MODEL}:generateContent?key={API_KEY}")
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "temperature": temperature},
    }).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.loads(r.read())
    except Exception as e:
        sys.exit(f"ERROR: Gemini API call failed: {e}")
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        sys.exit(f"ERROR: unexpected Gemini response: {str(data)[:300]}")
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        sys.exit(f"ERROR: Gemini did not return valid JSON: {text[:300]}")


# ── Prompts ─────────────────────────────────────────────────────────────────
def trend_prompt():
    return f"""You are a US social-trend researcher for a family-friendly quiz website. Today's date: {date.today().isoformat()}.
Return a JSON array of 10 topics trending in the last 48 hours in US TikTok/YouTube/pop culture that could become a fun quiz, riddle set, or trivia quiz.
Each item: {{"topic": "...", "evidence": "why it's trending", "angle": "quiz concept in 12 words", "format": "personality|trivia|riddle"}}.
EXCLUDE: politics, elections, tragedies, disasters, health/medical claims, misinformation-prone topics, hateful content.
Return ONLY the JSON array."""


def score_prompt(topics, published, n):
    return f"""You score quiz topics for a US mobile audience (18-44). Already published titles (do NOT repeat or closely duplicate): {published}.
Topics: {json.dumps(topics)}
Score each 1-10 on: us_appeal, click_reveal (urge to see result), video_ability (works as a 20s vertical video), evergreen_reuse.
Return a JSON array of the TOP {n} as {{"topic": "...", "format": "personality|trivia|riddle", "quiz_concept": "one-line quiz concept", "total": <sum of the 4 scores>}} sorted by total desc. Return ONLY the JSON array."""


def gen_prompt(concept, fmt):
    if fmt == "personality":
        q_spec = '{"q": "...", "options": ["a","b","c","d"], "scores": [0-40, 0-40, 0-40, 0-40]}'
    else:
        q_spec = '{"q": "...", "options": ["a","b","c","d"], "correct": 0-3}'
    return f"""You write original, family-friendly quizzes for QuizPop (US audience, grade-6 reading level).
Concept: {concept} | Format: {fmt}
Return ONLY this JSON object (no markdown, no commentary):
{{
 "title": "catchy title, max 60 chars",
 "slug": "url-slug-lowercase-hyphens",
 "hook": "one-line hook shown under the H1",
 "category": "personality|trivia|riddles",
 "seo_intro": "unique 150-200 word intro about this quiz topic",
 "tags": ["5", "short", "keywords", "us", "quiz"],
 "questions": [ exactly 6 items, each {q_spec} ],
 "results": [ exactly 3 items: {{"title": "...", "description": "40-80 words"}} ],
 "seo_title": "max 60 chars",
 "meta_description": "max 155 chars"
}}
Rules: 100% original wording (never copy existing quizzes); trivia/riddle answers must be well-established facts with exactly one correct option; personality results are fun, varied descriptions; NO medical/psychological diagnosis claims; NO politics/tragedy/health content."""


# ── Validation & normalization ──────────────────────────────────────────────
def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "quiz"


def thirds(results, max_score):
    """Fallback: split score range into equal thirds."""
    bounds = [(0, int(max_score * 0.4)),
              (int(max_score * 0.4) + 1, int(max_score * 0.79)),
              (int(max_score * 0.79) + 1, max_score)]
    out = []
    for r, (lo, hi) in zip(results, bounds):
        out.append({"min": lo, "max": hi, "t": r["title"], "d": r["description"]})
    return out


def normalize_quiz(q):
    """Validate + convert to the quiz.js score contract. Returns quiz dict or None."""
    try:
        fmt_trivia = "correct" in q["questions"][0]
        n = len(q["questions"])
        if not (5 <= n <= 8):
            return None
        questions = []
        for item in q["questions"]:
            opts = item["options"]
            if len(opts) != 4 or not all(isinstance(o, str) and o.strip() for o in opts):
                return None
            if fmt_trivia:
                ci = int(item["correct"])
                if not (0 <= ci <= 3):
                    return None
                scores = [100 if i == ci else 0 for i in range(4)]
            else:
                scores = [max(0, min(40, int(s))) for s in item["scores"]]
                if len(scores) != 4:
                    return None
            questions.append({"q": item["q"], "o": opts, "s": scores})
        max_score = n * (100 if fmt_trivia else 40)
        if len(q["results"]) != 3:
            return None
        results = thirds(q["results"], max_score)
        return {
            "title": q["title"][:80], "slug": slugify(q.get("slug") or q["title"]),
            "hook": q["hook"], "category": q["category"],
            "seo_intro": q["seo_intro"], "tags": q["tags"][:6],
            "questions": questions, "results": results,
            "seo_title": q["seo_title"][:70], "meta_description": q["meta_description"][:160],
        }
    except (KeyError, TypeError, ValueError):
        return None


# ── Rendering ───────────────────────────────────────────────────────────────
def render_page(q, related):
    tpl = (ROOT / "scripts" / "quiz_template.html").read_text()
    rel_html = "".join(
        f'<a href="/quiz/{r["slug"]}/">{html.escape(r["title"])}</a>' for r in related[:3]
    ) or '<div class="soon">More quizzes dropping daily<br><span class="soon-badge">Stay tuned</span></div>'
    page = tpl.replace("__SEO_TITLE__", html.escape(q["seo_title"], quote=True))
    page = page.replace("__META_DESCRIPTION__", html.escape(q["meta_description"], quote=True))
    page = page.replace("__H1__", html.escape(q["title"]))
    page = page.replace("__HOOK__", html.escape(q["hook"]))
    page = page.replace("__SEO_INTRO__", html.escape(q["seo_intro"]))
    page = page.replace("__RELATED_HTML__", rel_html)
    page = page.replace("__QUIZ_DATA_JSON__",
                        json.dumps({"questions": q["questions"], "results": q["results"]},
                                   ensure_ascii=False))
    return page


def write_sitemap(quizzes):
    urls = [DOMAIN + p for p in STATIC_PAGES]
    urls += [DOMAIN + f"quiz/{z['slug']}/" for z in quizzes]
    items = "\n".join(f'  <url><loc>{u}</loc><changefreq>weekly</changefreq></url>'
                      for u in urls)
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{items}\n</urlset>\n")


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    quizzes_path = ROOT / "quizzes.json"
    quizzes = json.loads(quizzes_path.read_text()) if quizzes_path.exists() else []
    existing_slugs = {z["slug"] for z in quizzes}
    published = [z["title"] for z in quizzes]

    print("Step 1/3: discovering trends…")
    topics = gemini(trend_prompt())
    print(f"  got {len(topics)} topics")

    print("Step 2/3: scoring topics…")
    picks = gemini(score_prompt(topics, published, PER_DAY))
    print("  picks:", [p.get("quiz_concept", "?")[:60] for p in picks])

    print("Step 3/3: generating quizzes…")
    new_quizzes = []
    for p in picks:
        raw = gemini(gen_prompt(p["quiz_concept"], p.get("format", "personality")),
                     temperature=1.0)
        q = normalize_quiz(raw)
        if not q:
            print(f"  SKIP (failed validation): {p.get('quiz_concept', '?')[:60]}")
            continue
        base, i = q["slug"], 2
        while q["slug"] in existing_slugs:
            q["slug"] = f"{base}-{i}"
            i += 1
        existing_slugs.add(q["slug"])
        new_quizzes.append(q)
        print(f"  OK: {q['title']}  (/quiz/{q['slug']}/)")

    if not new_quizzes:
        sys.exit("ERROR: no valid quizzes generated — nothing written.")

    # ── write phase (only reached if everything validated) ──
    for q in new_quizzes:
        related = [z for z in quizzes if z["slug"] != q["slug"]]
        page = render_page(q, related[-3:][::-1])
        outdir = ROOT / "quiz" / q["slug"]
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "index.html").write_text(page)
        quizzes.append({
            "slug": q["slug"], "title": q["title"], "category": q["category"],
            "tags": q["tags"], "description": q["meta_description"],
            "url": f"/quiz/{q['slug']}/", "questions_count": len(q["questions"]),
        })
    quizzes_path.write_text(json.dumps(quizzes, indent=2, ensure_ascii=False))
    write_sitemap(quizzes)
    print(f"DONE: {len(new_quizzes)} quizzes written.")


if __name__ == "__main__":
    main()
