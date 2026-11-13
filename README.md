# SiteWarrant

**Evidence-first website quality auditor.** It proves each finding with a measurement, ties symptoms
to one root cause, and re-audits after the fix.

> **Stage: phases P0–P7 have landed, except the public demo stand.** Discovery, eight deterministic
> channels at three viewports, eight budgeted agents behind a validator, deterministic deduplication
> and root causes with the Chief Auditor's narration, a frozen benchmark with published numbers, fixes
> with re-audits, and traces with cost estimates all run. The one item the plan still lists as open is
> a public URL for `infra/demo.yml`, which needs the owner's VPS and domain (PLAN §17.3).
>
> The numbers below come from stored runs under `evals/runs/`; a metric with no run behind it is
> `null` and says so, never `0`.

## The problem this solves

Point any scanner at a site and you get a wall of issues: the same defect counted four times, a
contrast failure with no element named, a "performance problem" with no measurement behind it, and no
way to tell what actually matters. SiteWarrant takes the opposite position — a finding exists only if
something was measured, and related symptoms are reported as one cause.

A cookie banner covering the primary CTA on a phone is one root cause with four consequences, not four
independent findings. That case is a required acceptance test, not an aspiration.

## What it audits

| Area | What is checked | MVP depth |
| --- | --- | --- |
| SEO | indexing, metadata, headings, canonical, sitemap, robots.txt, Schema.org, internal links | deep |
| Accessibility | WCAG 2.2 AA, keyboard navigation, ARIA, semantic HTML | deep |
| Performance | Core Web Vitals, LCP, CLS, TBT as INP proxy, JS and image weight | deep |
| Responsive | mobile, tablet, desktop, overflow, occlusion, touch targets | three viewports |
| Security | HTTPS, TLS, security headers, CSP, cookies, mixed content | passive checks |
| UI | typography, contrast, spacing, visual hierarchy, consistency | vision over screenshots |
| UX | navigation, user flows, CTAs, forms, information architecture | heuristic AI analysis |
| Conversion | value proposition, CTA clarity, trust elements, friction | heuristic estimate |

UX and Conversion are heuristics in the MVP and are labelled as such in the report. They are not
presented as measurements.

## How it works

```
URL
 └─ discovery        robots.txt, sitemap, BFS crawl, page-template clustering
     └─ fact layer    http_probe, dom_probe, axe-core, performance timings, screenshots (390/768/1440), occlusion
         └─ agents    8 specialised auditors read facts through MCP tools, write candidate findings
             └─ validator    schema, mandatory evidence reference, rule citation
                 └─ chief auditor   dedup, root-cause clustering, priority, business impact
                     └─ report      findings, screenshots, recommendations, measured impact
                         └─ re-audit    closed / persisting / new, plus regressions
```

The architectural rule that everything else follows: **deterministic tools collect facts, the LLM
interprets them.** A model is never asked to compute contrast ratios, read HTTP headers or measure
load time. Each finding must cite an observation produced by a tool, and a validator rejects findings
that cannot.

## Quality metrics

Measured on a labelled benchmark of 8 sites and 104 pages. Definitions and the matching rule live in
[docs/PLAN.md](docs/PLAN.md). Unless a row names another source, the value comes from
`evals/runs/2026-11-13-baseline-narration-v2.json` — corpus `sha256:df240161c8d3e5ea`, agent
`sha256:0a57261de95be73a`, 2026-11-13. A metric with no run behind it stays `null`.

| Metric | Definition | Value |
| --- | --- | --- |
| Findings precision | true positives / findings | `1.0000` — 80/80 |
| Findings recall | true positives / gold labels | `1.0000` — 80/80 |
| False positive rate | false positives / findings | `0.0000` — 0/80 |
| Duplicate finding rate | findings repeating the same page, rule and element | `0.0000` — 0/88 |
| Pages audited | pages in the benchmark run | 104 (8 sites; 80 planted defects, 24 clean pages) |
| Audit cost per 100 pages | estimated cost for 100 pages, extrapolated from one priced page | `$3.69` — an estimate, `0.036854 × 100`, from one fixture page with two agents ([report §3](docs/ENGINEERING_REPORT.md)); the corpus itself ran without agents, so there is no median across sites |
| Median audit duration | wall clock per audit | `3.06 s` per page — median of the run's 104 page durations, deterministic layer; the whole corpus took 327.6 s |
| Fix acceptance rate | accepted fixes / proposed fixes | `null` — no run artifact; the patch behaviour is pinned by `tests/test_fixes_patch.py` and `tests/integration/test_fixes_audit.py` |
| Regression-free fix rate | re-audits with no new finding at all / applied fixes | `null` — no run artifact; re-audit behaviour is pinned by the same tests, on the fixture only |

A zero denominator reports `null`, never `0`. Cost is an estimate from a versioned price table; tokens
and call counts are the measured, tariff-independent values reported next to it.

## Scope of the MVP

Planned for 8 weeks of evening work, roughly 80 hours. That is an estimate, not a commitment.

| Phase | Weeks | Deliverable | State |
| --- | --- | --- | --- |
| P0 | 1 | repository skeleton, CLI, one page to one report | **done** |
| P1 | 1–2 | crawl, discovery, page templates | **done** |
| P2 | 2–3 | deterministic fact layer, three viewports | **done** |
| P3 | 3–4 | MCP tools, orchestrator, 8 agents, rule corpus | **done** |
| P4 | 4–5 | chief auditor, root causes, web report | **done** (deterministic grouping, narrated clusters, CI screenshot) |
| P5 | 5–6 | benchmark, gold labels, eval runner | **done** |
| P6 | 6–7 | fixes and re-audit with diff | **done** |
| P7 | 7–8 | tracing, cost accounting, demo, engineering report | **done, except the public demo stand** |

**Not in the MVP:** accounts and billing, scanning behind authentication, opening pull requests in
third-party repositories, mobile apps, browser extensions, PDF export, UI localisation.

## What this is not

Not a replacement for Lighthouse, Screaming Frog, Siteimprove, Semrush, BrowserStack or WAVE. The value
is the opposite direction: combining their measurements, interpreting them together, finding the shared
cause, and verifying that a fix actually fixed something.

## Quick start

```bash
docker compose -f infra/docker-compose.yml up -d --wait   # Postgres, Redis, fixture site
cd api && uv sync && uv run alembic upgrade head
uv run sitewarrant crawl http://localhost:8081/ --allow-private --out pages.json
uv run sitewarrant audit http://localhost:8081/ --allow-private --out report.json
```

The fixture site at `http://localhost:8081/` is a static page with ten defects planted on purpose,
one per rule in `api/app/rules/catalog.py`, plus a journal, a product list, an app shell and a
sitemap for the crawler. `--allow-private` is required because the request guard refuses loopback
addresses by default; without the flag both commands exit with code 2. The flag exempts only the
named host, so a redirect from that host to a private address is still refused.

Exit codes: `0` no blocker, `1` a blocker was proven, `2` the run itself failed.

## Verification

Measured on 2026-11-13 against the fixture site, agent `sha256:0a57261de95be73a` (axe-core 4.14.0,
10 SiteWarrant rules):

- 14 findings from the ten planted defects: `blocker=2 major=11 minor=1 info=0`. The banner
  covers five separate links, and each covered target is its own finding — collapsing them would
  hide four defects behind the first one's summary.
- Exit code `1`, because two blockers were proven.
- Every finding carries at least one evidence item, and every cited `observation_id` resolves to a
  stored row — asserted by `tests/integration/test_audit_fixture.py`.
- Two consecutive runs on the same page report the same rule set.
- Backend gate: `ruff`, `ruff format --check`, `mypy --strict`, 354 tests green (301 unit, 53 integration).
- Frontend gate: `biome check`, `tsc --noEmit`, `next build` green.
- `robots.txt` is enforced by default: the fixture disallows `/blocked.html`, and auditing it exits with
  code 2 unless `--ignore-robots` is passed.
- A redirect to a private address is refused: `/to-private` bounces to `169.254.169.254` and the audit
  fails with "request guard blocked", even though the fixture host itself is allowed.
- A page with `Content-Security-Policy: script-src 'self'` is still audited: axe runs through
  `Runtime.evaluate`, not an injected script element.
- The crawl of the fixture finds 13 pages and selects 9: `/blog/post-*.html` has 3 pages and keeps 2,
  `/blocked.html` is skipped by robots, `/about` and `/contact` are recorded as `http_404`, and
  `/spa.html` is re-read through the browser because its body ships empty.
- A sitemap entry on another host is not followed, and a sitemap entry that robots.txt disallows is not
  fetched.
- Eight channels report 59 observations on the fixture page, each viewport named in its observation:
  `http=8 dom=3 axe=27 contrast=9 responsive=3 occlusion=3 performance=3 screenshot=3`.
- A finding carries one evidence item per measurement behind it: a defect measured at three viewports
  carries three, an axe violation reported at two viewports carries six, and a page-level finding
  carries one. The same defect at 390, 768 and 1440 px is one finding, not three.
- Three snapshots per page, one per viewport, with HTML, DOM JSON and a full-page PNG on disk.
- Two consecutive audits produce an identical observation set once timings and artifact keys are
  excluded; `tests/integration/test_fact_layer.py` asserts that.
- The eval corpus is frozen: `python benchmark/generate.py --check` fails when a page and its labels
  drift apart, and the same corpus scores the same numbers twice
  (`tests/integration/test_eval_corpus.py`).
- Eight agents share one budgeted loop (12 tool calls, 60k tokens as a warning with two reserved
  calls, 180 s deadline) and read facts through an
  MCP server scoped to their audit; the validator rejects a finding whose observation does not exist,
  whose number is not in the cited payload, or whose accessibility claim cites no WCAG criterion.
- A real run with `--agents a11y` against the fixture reports 15 findings — the 14 deterministic
  ones plus one `A11Y-TARGET-SIZE` citing WCAG 2.2 SC 2.5.8 — and the same single root cause.
  On the pre-P4 revision (`agent sha256:77ad5403f8fe400f`, 9 deterministic rules) the same fixture
  produced 18 findings with `--agents seo,a11y`: nine deterministic, three from seo and six
  `A11Y-TARGET-SIZE`, one per small target, each distinguished by its `subject`.
- A failed agent does not fail the audit: the report carries `status: partial` and the deterministic
  findings stay. `tests/integration/test_agents_audit.py` pins both behaviours on cassettes.
- The fixture's banner — which covers the header navigation at 390 px and carries a nameless link —
  is one root cause (`header`) with six symptoms from `responsive` and `a11y`, not unrelated
  findings: `summary.root_causes` is 1 and `duplicate_rate` is 0 on the deterministic run.
- With `--agents a11y` and narration on, the report carries a `chief` row next to the agent's: one
  model call, `tokens_in` 1146, `tokens_out` 863, `cost_estimate_usd` 0.001379 as an estimate, and the
  root cause's `summary` is a sentence about the header instead of the measured sentence. When the
  reply names a number the cluster's facts do not contain, the measured sentence stays and the reason
  is in `summary.agents[chief].error`; `tests/integration/test_chief_audit.py` pins both. The run is
  stored as `evals/audits/2026-11-13-fixture-narrated.json`.
- Duplicates merge only when the findings share a subject (compared as written, CSS selectors are
  case-sensitive) or a citation, so two targets in one block stay two findings and the same target
  measured at three viewports is one.

This is a single page of ten known defects. It is not precision, not recall, and not a benchmark.

## Benchmark and evals

The corpus is eight synthetic sites, thirteen pages each, with one defect per catalogued rule per
site and three clean pages per site as the control for false positives. It is generated, not
hand-edited, and frozen:

```bash
cd api                                        # `uv run` needs this project
python3 ../benchmark/generate.py --check       # every page still matches the generator
uv run sitewarrant eval --dataset ../benchmark --out ../evals/runs/latest.json
```

Measured on 2026-11-13 over the whole corpus (104 pages, 80 planted defects, agent
`sha256:0a57261de95be73a`, 327.6 s, `evals/runs/2026-11-13-baseline-narration-v2.json`):

- precision `1.0` (80/80), recall `1.0` (80/80), false-positive rate `0.0` (0/80);
- pages with at least one unlabelled finding: `0/104`; duplicate rate `0.0` (0/88);
- every rule scores 8/8 on its own denominators.

A perfect score here is a floor, not a claim about the open web: the generator plants exactly the
defects the catalogue promises to catch, so `1.0` means "no planted defect was lost and nothing was
invented". Precision on real sites is what an eval run against real sites would measure — this
corpus cannot.

Two runs on the same corpus compare with `--compare`, and a comparison across different corpora is
refused rather than reported.

## Fixes and re-audit

```bash
cd api
uv run sitewarrant fix <audit_id> --site-dir ../benchmark/fixtures/site --out fixes/<audit_id>
uv run sitewarrant reaudit <audit_id> --against-report old.json \
    --patch fixes/<audit_id>/fixes.patch --site-dir ../benchmark/fixtures/site
```

`fix` writes a recommendation for every finding and a unified diff for the five rules that can be
repaired without inventing text (`SEO-TITLE`, `SEO-META-DESC`, `SEO-H1`, `A11Y-LANG`,
`LAYOUT-OCCLUSION`). `reaudit` applies that diff to a copy of the site, serves the copy on loopback,
audits it again and reports closed / remaining / new — every new finding counts as a regression and
the command exits `1`.

## Traces and cost

Every audit records one trace: `audit → page → agent → tool call → model call`, with
OpenTelemetry's identifiers and a `trace.jsonl` artifact beside the report. The report's summary says
which trace it was (`trace_id`), how many spans of each kind it holds, how many tokens the model
actually used, and what those tokens would cost at the versioned price file:

```json
"tokens_in": 13991, "tokens_out": 1237, "llm_calls": 6,
"cost_estimate_usd": 0.004682,
"pricing": {"version": "2026-11-13", "basis": "list price ...", "unpriced_models": []}
```

Tokens and call counts are measured; `cost_estimate_usd` is an estimate from
`pricing/pricing.yaml`, and the audit stores the price version it was measured with, so an old run is
never silently re-priced. A model with no entry in that file gets `null`, never `0.0` — "not priced"
and "free" are different claims. `SITEWARRANT_AUDIT_COST_LIMIT_USD` (default `0.25`) stops an agent
that reaches the ceiling; it reports `budget_exceeded` instead of finishing the page.

The Chief Auditor's explanation of a cluster is one more model call, recorded as the `chief` row in
`summary.agents` and in `llm_calls`, so its tokens and estimate sit next to the agents'. It explains
groups that already exist and never re-groups them; a sentence that names a number the cluster's
facts do not contain is dropped and the measured wording stays, which is why the report can show a
plain sentence when the provider is unreachable. `SITEWARRANT_CHIEF_NARRATION=0` turns it off.

A proposed prompt change is accepted only if precision does not regress:

```bash
uv run sitewarrant prompt-check --baseline ../evals/runs/base.json --candidate ../evals/runs/new.json
```

## Demo

`infra/demo.yml` runs the same code as one command, with the API bound to loopback; the public face
is a TLS proxy in front of it, because an unauthenticated crawler should not answer on `0.0.0.0`.

```bash
POSTGRES_PASSWORD=change-me SITEWARRANT_LLM_API_KEY=... \
  docker compose -f infra/demo.yml up -d --build
curl -s -X POST http://127.0.0.1:8000/audits -H 'content-type: application/json' \
  -d '{"url": "https://example.com"}'
# {"audit_id": "...", "status": "running"} — the run continues in the process
curl -s http://127.0.0.1:8000/audits/<audit_id>          # poll until status is completed
curl -s http://127.0.0.1:8000/audits/<audit_id>/report | head -c 400
```

The Next.js interface reads the same endpoints through a server-side rewrite: `/` lists the sites
with a report, `/audits` polls the current and recent runs, `/audits/new` starts one. Set
`SITEWARRANT_API` (default `http://127.0.0.1:8000`) and run `bun run dev` from `web/`.

The stack is not deployed on a public URL yet: that needs the VPS and a domain, which is the owner's
call (PLAN §17.3).

## Layout

```
api/          FastAPI service, crawler, audit tools, agents, evals, MCP server
web/          Next.js interface: audited sites, audit form, progress, report
benchmark/    site manifest, gold labels, CI fixtures
rules/        WCAG 2.2, SEO and HTTP security rule corpus
infra/        docker-compose, images, egress limits
docs/         PLAN.md, ENGINEERING_REPORT.md
```

## Requirements

- Python 3.12 with [`uv`](https://docs.astral.sh/uv/)
- [Bun](https://bun.sh/) for the web app
- Docker with Compose, for Postgres, Redis and the fixture site
- Chromium for Playwright: `cd api && uv run playwright install chromium`

Full commands, including the single `make check` gate, are in [AGENTS.md](AGENTS.md).

## Documentation

| Document | Answers |
| --- | --- |
| [docs/PLAN.md](docs/PLAN.md) | what is being built, in what order, how it is measured — **authoritative** |
| [AGENTS.md](AGENTS.md) | how to work in this repository, invariants, boundaries, pitfalls |
| [idea.md](idea.md) | the original product concept |
| [.agents/plans/2026-11-12-naming.md](.agents/plans/2026-11-12-naming.md) | why the project is named SiteWarrant |

If a document disagrees with `docs/PLAN.md`, the plan is right and the other document is corrected in
the same change.

## License

Not chosen yet. Tracked as an open question in [docs/PLAN.md](docs/PLAN.md).
