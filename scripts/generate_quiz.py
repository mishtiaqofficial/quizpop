#!/usr/bin/env python3
"""
QuizPop daily content pipeline — runs on GitHub Actions (free tier).
Trend discovery -> topic scoring -> quiz generation (Gemini API) ->
writes quiz pages -> updates quizzes.json + sitemap.xml.

Stdlib only. Two-phase: all quizzes are generated and validated BEFORE
anything is written, so a failure never leaves a half-built site.

Env:
  GEMINI_API_KEY   required (GitHub repo secret)
  GEMINI_MODEL     default: gemini-3.5-flash
  QUIZZES_PER_DAY  default: 3
  SITE_DOMAIN      default: https://popquizdaily.site/
"""
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # repo root (quizpop-site contents)
API_KEY = os.environ.get("GEMINI_API_KEY", "")
PER_DAY = int(os.environ.get("QUIZZES_PER_DAY", "3"))
DOMAIN = os.environ.get("SITE_DOMAIN", "https://popquizdaily.site/").rstrip("/") + "/"

STATIC_PAGES = ["", "personality/", "trivia/", "riddles/", "trending/",
                "search/", "about/", "contact/", "privacy/", "terms/", "disclosure/"]

# ── SEO keyword targets (research 2026-09-29, quizpop-keyword-research-20260929-1818).
# Low-competition long-tail keywords for US/UK/CA/AU. Priority order: easiest wins first.
# The pipeline works through these in order, skipping anything already published.
KEYWORD_TARGETS = [
    # priority 1 — easiest wins
    {"kw": "what is my aesthetic quiz", "cluster": "decade/aesthetic", "angle": "which aesthetic are you (cottagecore, dark academia, Y2K, minimal)?"},
    {"kw": "short love language quiz no sign up", "cluster": "love", "angle": "5-question version, result shown instantly with no email"},
    {"kw": "career quiz for teens", "cluster": "career/money", "angle": "fun career matcher for teens — no boring aptitude-test tone"},
    {"kw": "free career quiz for adults no sign up", "cluster": "career/money", "angle": "quick career-path finder, instant result, no email wall"},
    {"kw": "money personality quiz", "cluster": "career/money", "angle": "are you a saver, spender, investor or giver?"},
    {"kw": "which decade do i belong in quiz", "cluster": "decade/aesthetic", "angle": "alternate phrasing of our decade quiz — 60s/70s/80s/90s/2000s"},
    # priority 2
    {"kw": "love language quiz for couples", "cluster": "love", "angle": "couples edition — compare your love languages"},
    {"kw": "what is my love language test", "cluster": "love", "angle": "full 5-love-languages test, instant result"},
    {"kw": "which disney princess am i quiz", "cluster": "decade/aesthetic", "angle": "original wording — personality-mapped princess results"},
    {"kw": "what kind of witch am i quiz", "cluster": "decade/aesthetic", "angle": "cottage witch, sea witch, kitchen witch..."},
    {"kw": "which greek god are you quiz", "cluster": "decade/aesthetic", "angle": "zeus, athena, apollo, artemis..."},
    {"kw": "what dessert am i quiz", "cluster": "food", "angle": "which dessert matches your personality"},
    {"kw": "which pizza topping are you quiz", "cluster": "food", "angle": "fun food-personality quiz"},
    {"kw": "morning person or night owl quiz", "cluster": "decade/aesthetic", "angle": "chronotype quiz with fun results"},
    # priority 3 — high-volume, medium competition
    {"kw": "hard trivia questions for adults with answers", "cluster": "trivia", "angle": "50-question listicle-style quiz, hidden answers"},
    {"kw": "tricky riddles for adults with answers", "cluster": "riddles", "angle": "30-riddle collection, answers revealed as you play"},
    {"kw": "fun quizzes to take when bored", "cluster": "decade/aesthetic", "angle": "boredom-buster personality quiz"},
    {"kw": "what should i be for halloween quiz", "cluster": "seasonal", "angle": "costume picker quiz"},
    {"kw": "am i in love quiz", "cluster": "love", "angle": "signs-you're-in-love checklist quiz"},
    {"kw": "does he like me quiz", "cluster": "love", "angle": "does-he-like-me signs quiz for teens"},
]

# Seasonal overrides: if today falls in a window, one quiz MUST target the seasonal keyword.
# Windows start 6-8 weeks before the holiday so Google can index in time.
SEASONAL_WINDOWS = [
    ("08-15", "10-31", {"kw": "halloween personality quiz", "cluster": "seasonal",
        "angle": "which halloween monster/character are you"}),
    ("09-15", "11-30", {"kw": "thanksgiving quiz", "cluster": "seasonal",
        "angle": "which thanksgiving food are you"}),
    ("10-15", "12-28", {"kw": "christmas personality quiz", "cluster": "seasonal",
        "angle": "which christmas movie character are you"}),
    ("11-15", "01-10", {"kw": "new year quiz", "cluster": "seasonal",
        "angle": "what will the new year bring you"}),
    ("12-20", "02-14", {"kw": "valentine's day quiz", "cluster": "seasonal",
        "angle": "what's your valentine's love style"}),
]


# ── Gemini REST call (stdlib only) ──────────────────────────────────────────
def discover_models():
    """Ask the API which models this key can actually use right now.

    Self-healing: retired or overloaded models are simply absent from the
    list, so the pipeline never again dies because a hardcoded model name
    stopped working."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.loads(r.read())
    except Exception:
        return []
    names = []
    for m in data.get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            name = m.get("name", "").replace("models/", "")
            if name:
                names.append(name)
    return names


def candidate_models():
    """Preferred model first, then other flash models, then anything else."""
    preferred = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
    ordered = []
    for m in [preferred] + discover_models():
        if m and m not in ordered:
            ordered.append(m)
    flash = [m for m in ordered if "flash" in m.lower()]
    rest = [m for m in ordered if m not in flash]
    return flash + rest or [preferred]


def gemini(prompt, temperature=0.9):
    if not API_KEY:
        sys.exit("ERROR: GEMINI_API_KEY is not set.")
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "temperature": temperature},
    }).encode()
    last_err = None
    for model in candidate_models():
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={API_KEY}")
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            # 404 = retired, 429 = rate-limited, 5xx = overloaded → try next model
            if e.code in (404, 429, 500, 502, 503):
                print(f"WARN: model {model} unavailable (HTTP {e.code}), trying next…",
                      flush=True)
                last_err = e
                continue
            sys.exit(f"ERROR: Gemini API call failed: {e}")
        except Exception as e:
            sys.exit(f"ERROR: Gemini API call failed: {e}")
        print(f"INFO: using Gemini model {model}", flush=True)
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            sys.exit(f"ERROR: unexpected Gemini response: {str(data)[:300]}")
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            sys.exit(f"ERROR: Gemini did not return valid JSON: {text[:300]}")
    sys.exit(f"ERROR: all Gemini models failed, last error: {last_err}")


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


def gen_prompt(concept, fmt, target_kw=None):
    if fmt == "personality":
        q_spec = '{"q": "...", "options": ["a","b","c","d"], "scores": [0-40, 0-40, 0-40, 0-40]}'
    else:
        q_spec = '{"q": "...", "options": ["a","b","c","d"], "correct": 0-3}'
    kw_line = (f"TARGET KEYWORD (US search): \"{target_kw}\" — the quiz title, seo_title and meta_description "
               f"must target this exact phrase; the seo_intro must answer it.\n" if target_kw else "")
    return f"""You write original, family-friendly quizzes for QuizPop (US audience, grade-6 reading level).
Concept: {concept} | Format: {fmt}
{kw_line}Return ONLY this JSON object (no markdown, no commentary):
{{
 "title": "catchy title, max 60 chars",
 "slug": "url-slug-lowercase-hyphens",
 "hook": "one-line hook shown under the H1",
 "category": "personality|trivia|riddles",
 "seo_intro": "unique 150-200 word intro about this quiz topic",
 "tags": ["5", "short", "keywords", "us", "quiz"],
 "questions": [ exactly 6 items, each {q_spec} ],
 "results": [ exactly 3 items: {{"title": "...", "description": "40-80 words"}} ],
 "seo_title": "max 50 chars (site appends — QuizPop, keep total under 60)",
 "meta_description": "max 155 chars",
 "faq": [ exactly 3 items: {{"q": "a real 'people also ask' style question about this quiz topic", "a": "helpful 1-2 sentence answer, 40-60 words"}} ]
}}
Rules: 100% original wording (never copy existing quizzes); trivia/riddle answers must be well-established facts with exactly one correct option; personality results are fun, varied descriptions; NO medical/psychological diagnosis claims; NO politics/tragedy/health content; seo_title should contain the target keyword phrase naturally; the first FAQ question should directly answer the target keyword query."""


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
            "faq": [{"q": str(i.get("q", ""))[:200], "a": str(i.get("a", ""))[:400]}
                    for i in (q.get("faq") or [])[:3]
                    if isinstance(i, dict) and i.get("q") and i.get("a")],
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
    page = page.replace("__CANONICAL_URL__", f"{DOMAIN}quiz/{q['slug']}/")
    page = page.replace("__H1__", html.escape(q["title"]))
    page = page.replace("__HOOK__", html.escape(q["hook"]))
    page = page.replace("__SEO_INTRO__", html.escape(q["seo_intro"]))
    page = page.replace("__RELATED_HTML__", rel_html)
    page = page.replace("__QUIZ_DATA_JSON__",
                        json.dumps({"questions": q["questions"], "results": q["results"]},
                                   ensure_ascii=False))
    # FAQ: visible PAA answers + FAQPage schema
    faq_items = q.get("faq") or []
    if faq_items:
        faq_html = "".join(
            f'<p><strong>{html.escape(i["q"])}</strong> {html.escape(i["a"])}</p>'
            for i in faq_items)
        schema = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": i["q"],
             "acceptedAnswer": {"@type": "Answer", "text": i["a"]}} for i in faq_items]}
        faq_block = faq_html + ('<script type="application/ld+json">' +
                                json.dumps(schema, ensure_ascii=False) + '</script>')
    else:
        faq_block = ""
    page = page.replace("__FAQ_BLOCK__", faq_block)
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


def in_window(start, end, today=None):
    """MM-DD window check, handles year wraparound (e.g. 12-20 -> 01-10)."""
    today = today or date.today()
    mmdd = today.strftime("%m-%d")
    if start <= end:
        return start <= mmdd <= end
    return mmdd >= start or mmdd <= end


def pick_concepts(published_slugs, published_titles, n):
    """Return n quiz concepts: seasonal override first, then keyword targets,
    then fall back to trend discovery. Each item: (concept, format, target_kw)."""
    concepts = []
    covered = " ".join(published_slugs + published_titles).lower()

    # 1. seasonal override
    for start, end, target in SEASONAL_WINDOWS:
        if in_window(start, end):
            if target["kw"].split()[0] not in covered:
                concepts.append((target["angle"], "personality", target["kw"]))
                covered += " " + target["kw"]
            break

    # 2. keyword targets in priority order
    for target in KEYWORD_TARGETS:
        if len(concepts) >= n:
            break
        key = target["kw"].split()[0]
        if key in covered:
            continue
        fmt = "personality"
        if target["cluster"] in ("trivia",):
            fmt = "trivia"
        elif target["cluster"] in ("riddles",):
            fmt = "riddle"
        concepts.append((target["angle"], fmt, target["kw"]))
        covered += " " + target["kw"]

    # 3. trend discovery fills any remaining slots
    if len(concepts) < n:
        print(f"Step 1/3: discovering trends ({n - len(concepts)} slots)…")
        topics = gemini(trend_prompt())
        picks = gemini(score_prompt(topics, published_titles, n - len(concepts)))
        for p in picks:
            concepts.append((p["quiz_concept"], p.get("format", "personality"), None))
    else:
        print("Step 1/3: keyword targets cover all slots — skipping trend discovery.")
    return concepts


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    quizzes_path = ROOT / "quizzes.json"
    quizzes = json.loads(quizzes_path.read_text()) if quizzes_path.exists() else []
    existing_slugs = {z["slug"] for z in quizzes}
    published = [z["title"] for z in quizzes]
    published_slugs = [z["slug"] for z in quizzes]

    concepts = pick_concepts(published_slugs, published, PER_DAY)

    print("Step 2/3: generating quizzes…")
    new_quizzes = []
    for concept, fmt, target_kw in concepts:
        raw = gemini(gen_prompt(concept, fmt, target_kw), temperature=1.0)
        q = normalize_quiz(raw)
        if not q:
            print(f"  SKIP (failed validation): {concept[:60]}")
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
