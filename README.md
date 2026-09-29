# QuizPop — static site scaffold

Mobile-first static quiz site. No frameworks, no build step. Deploy target: **Cloudflare Pages** (free).

## Deploy (Cloudflare Pages)

1. `cd quizpop-site && git init && git add . && git commit -m "QuizPop scaffold"`
2. Push to GitHub (private repo recommended).
3. Cloudflare dashboard → Pages → Create → Connect Git → select repo.
4. Build settings: **no build command**, output directory: `/` (repo root = site root).
5. Deploy. You get `https://quizpop.pages.dev` instantly; add your custom domain later in Pages → Custom domains.

## Before launch — replace these placeholders

| Placeholder | Where | Replace with |
|---|---|---|
| `YOUR_MONETAG_SMARTLINK` | `assets/js/tracking.js` (**one place only**) | Your real Monetag Direct Link (Dashboard → Sites → Add zone → Direct Link). Keep it out of public repos. |
| `https://quizpop.example/` | `sitemap.xml`, `.github/workflows/daily-quiz.yml` (`SITE_DOMAIN`) | Your real domain — set once the live URL is confirmed |
| GA4 snippet | Before `</body>` on every page (see `<!-- GA4 -->` comments) | Your `G-XXXXXXXXXX` measurement snippet |

## Add a new quiz (2 minutes)

1. Copy `quiz/7-tricky-riddles/` → `quiz/your-slug/`.
2. Edit `index.html`: title, meta description, H1, hero text, FAQ.
3. Replace `window.QUIZ_DATA` with your questions. Three modes supported:
   - **Score** (personality): `{ q, o:[4], s:[4 weights] }` + results `{min,max,t,d}`
   - **Trivia** (right/wrong): `{ q, o:[4], correct: index }` + results by correct-count ranges
   - **Category** (tally): `{ q, o:[4], cat:[4 keys] }` + results `{key,t,d}`
4. Update the "Keep playing" related links.
5. Append the quiz to `quizzes.json` (powers `/search/`) and add its URL to `sitemap.xml`.
6. Replace one "Coming soon" card on the matching category page with a real link card.

## How the SmartLink funnel works

- The SmartLink lives **only** on `a[data-smartlink]` buttons inside the labeled **Sponsored** block on quiz pages.
- `assets/js/tracking.js` attaches UTM params at click-time (`utm_source` from `?src=`, `utm_medium=smartlink`, `utm_campaign=quiz_funnel`, `utm_content=page__cta`), fires a GA4 `smartlink_click` event, and keeps a `localStorage` backup log.
- Link opens in a new tab (`target="_blank" rel="noopener sponsored"`).

## Compliance reminders (non-negotiable)

1. **Results are never gated.** The full result always renders on-page. Never hide it behind the sponsored click.
2. **CTA always labeled "Sponsored"** with the FTC note adjacent. Never style it as quiz content ("See results", "Next").
3. **Never auto-fire** the SmartLink — no on-load, on-scroll, on-complete, or exit redirects.
4. **Never post the raw SmartLink on social.** Social posts link to quiz pages (`?src=tiktok` etc.); the bridge page protects your accounts.
5. **One account, real traffic only.** No bots, no bought clicks, no incentivized traffic — Monetag bans for this and withholds balances (Terms §§8, 15).

## File inventory

```
quizpop-site/
├── index.html                      homepage
├── personality/index.html          category page
├── trivia/index.html                category page
├── riddles/index.html               category page
├── trending/index.html              ranked by weekly plays
├── search/index.html                client-side search over quizzes.json
├── about/index.html
├── contact/index.html
├── privacy/index.html
├── terms/index.html
├── disclosure/index.html            FTC plain-English statement
├── quiz/
│   ├── which-decade-do-you-belong-in/index.html   (score mode)
│   ├── 7-tricky-riddles/index.html                (trivia mode)
│   └── whats-your-love-language/index.html        (category mode)
├── quizzes.json                     search index (3 quizzes)
├── sitemap.xml                       14 pages, placeholder domain
├── assets/css/style.css              design system
└── assets/js/
    ├── quiz.js                       generic quiz engine + share
    └── tracking.js                   SmartLink UTM + click tracking
```

20 files total. Re-verify Monetag's Terms (monetag.com/terms) before launch — policies change, and the live documents are the only authority.

---

## 🤖 Daily automation — GitHub Actions (free, $0)

The `scripts/` + `.github/` folders turn the site into a self-running content machine. Every day at **08:00 PKT** it discovers US trends, scores topics, generates quizzes with Gemini, writes the pages, and updates `quizzes.json` + `sitemap.xml`.

**One-time setup (10 minutes):**
1. Create a GitHub repo and push the **contents** of this folder as the repo root (so `index.html` sits at the top level).
2. Get a free Gemini API key at https://aistudio.google.com/ (free tier is plenty for 3 quizzes/day).
3. Repo → **Settings → Secrets and variables → Actions → New repository secret** → name `GEMINI_API_KEY`, paste the key.
4. Repo → **Actions** tab → enable workflows → run **"Daily Quiz Pipeline"** once manually to test.
5. **Cloudflare Pages** → Create project → connect the repo → build settings: *none* (static), output directory `/`. Every push auto-deploys.

**How it works:**
- `scripts/generate_quiz.py` — stdlib-only Python. Phase 1: trend discovery → Phase 2: topic scoring (skips already-published titles) → Phase 3: quiz generation. Files are written only after all quizzes pass validation, so a failure never leaves a half-built site.
- `scripts/quiz_template.html` — the page template. New quizzes get the same layout, Sponsored CTA block, FTC note, and tracking scripts as the hand-built ones.
- `.github/workflows/daily-quiz.yml` — runs daily at 03:00 UTC (08:00 PKT). Change the `cron` line to adjust. `workflow_dispatch` lets you run it manually with a custom quiz count.

**Cost:** $0 — GitHub Actions free tier (2,000 min/month; this job uses ~2 min/day), Gemini free tier, Cloudflare Pages free.

**Quality control:** the script validates every quiz (6 questions, 4 options, sane score ranges) and auto-skips anything malformed. Spot-check new quizzes weekly — AI drafts are good but you're the editor.

**To pause:** Actions → "Daily Quiz Pipeline" → Disable workflow.

> ⚠️ Replace `https://quizpop.example/` with your real domain in the workflow file (`SITE_DOMAIN`) and in `sitemap.xml` before launch.
