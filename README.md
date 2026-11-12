# SiteWarrant

**Evidence-first website quality auditor.** It proves each finding with a measurement, ties symptoms
to one root cause, and re-audits after the fix.

> **Stage: phase P0 complete. The vertical slice runs; the platform does not exist yet.**
> `sitewarrant audit <url>` crawls one page, runs axe-core and a DOM probe, and writes a JSON report
> where every finding cites a stored observation. Crawling, the eight audit agents, root-cause
> clustering, evals and re-audits are still ahead — see the phase table below.
>
> The quality metrics are `null`: there is no eval run yet, and no number here was produced by a
> benchmark. The only measured facts in this repository are the fixture results described under
> "Verification".

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
     └─ fact layer    http_probe, dom_probe, axe-core, Lighthouse, screenshots (390/768/1440), occlusion
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

Measured on a labelled benchmark of 8 sites and 100+ pages. Definitions and the matching rule live in
[docs/PLAN.md](docs/PLAN.md).

| Metric | Definition | Value |
| --- | --- | --- |
| Findings precision | true positives / findings | `null` — no eval run yet |
| Findings recall | true positives / gold labels | `null` — no eval run yet |
| False positive rate | false positives / findings | `null` — no eval run yet |
| Duplicate finding rate | findings repeating the same page, rule and element | `null` — no eval run yet |
| Pages audited | pages in the benchmark run | `null` — no eval run yet |
| Audit cost per 100 pages | estimated cost, median across sites | `null` — no eval run yet |
| Median audit duration | wall clock per audit | `null` — no eval run yet |
| Fix acceptance rate | accepted fixes / proposed fixes | `null` — no eval run yet |
| Regression-free fix rate | re-audits with no new blocker or major / applied fixes | `null` — no eval run yet |

A zero denominator reports `null`, never `0`. Cost is an estimate from a versioned price table; tokens
and call counts are the measured, tariff-independent values reported next to it.

## Scope of the MVP

Planned for 8 weeks of evening work, roughly 80 hours. That is an estimate, not a commitment.

| Phase | Weeks | Deliverable | State |
| --- | --- | --- | --- |
| P0 | 1 | repository skeleton, CLI, one page to one report | **done** |
| P1 | 1–2 | crawl, discovery, page templates | not started |
| P2 | 2–3 | deterministic fact layer, three viewports | not started |
| P3 | 3–4 | MCP tools, orchestrator, 8 agents, rule corpus | not started |
| P4 | 4–5 | chief auditor, root causes, web report | not started |
| P5 | 5–6 | benchmark, gold labels, eval runner | not started |
| P6 | 6–7 | fixes and re-audit with diff | not started |
| P7 | 7–8 | tracing, cost accounting, demo, engineering report | not started |

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
uv run sitewarrant audit http://localhost:8081/ --allow-private --out report.json
```

The fixture site at `http://localhost:8081/` is a static page with nine defects planted on purpose,
one per rule in `api/app/rules/catalog.py`. `--allow-private` is required because the request guard
refuses loopback addresses by default; without the flag the audit exits with code 2. The flag exempts
only the audited host, so a redirect from that host to a private address is still refused.

Exit codes: `0` no blocker, `1` a blocker was proven, `2` the audit itself failed.

## Verification

Measured on 2026-11-12 against the fixture site, agent `sha256:4aa361ad4176c48c` (axe-core 4.14.0,
9 rules):

- 9 findings, one per planted defect: `blocker=2 major=6 minor=1 info=0`.
- Exit code `1`, because two blockers were proven.
- Every finding carries at least one evidence item, and every cited `observation_id` resolves to a
  stored row — asserted by `tests/integration/test_audit_fixture.py`.
- Two consecutive runs on the same page report the same rule set.
- Backend gate: `ruff`, `ruff format --check`, `mypy --strict`, 59 tests green (46 unit, 13 integration).
- Frontend gate: `biome check`, `tsc --noEmit`, `next build` green.
- `robots.txt` is enforced by default: the fixture disallows `/blocked.html`, and auditing it exits with
  code 2 unless `--ignore-robots` is passed.
- A redirect to a private address is refused: `/to-private` bounces to `169.254.169.254` and the audit
  fails with "request guard blocked", even though the fixture host itself is allowed.
- A page with `Content-Security-Policy: script-src 'self'` is still audited: axe runs through
  `Runtime.evaluate`, not an injected script element.

This is a single page of nine known defects. It is not precision, not recall, and not a benchmark.

## Layout

```
api/          FastAPI service, crawler, audit tools, agents, evals, MCP server
web/          Next.js report interface
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
