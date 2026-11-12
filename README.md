# SiteWarrant

**Evidence-first website quality auditor.** It proves each finding with a measurement, ties symptoms
to one root cause, and re-audits after the fix.

> **Stage: specification. There is no code yet.**
> Every number in this repository today is a target or an estimate. Nothing here has been measured.
> When the first eval run exists, its numbers replace the `null` values below and carry the date
> and denominator of that run.

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
| P0 | 1 | repository skeleton, CLI, one page to one report | not started |
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

## Planned layout

```
api/          FastAPI service, crawler, audit tools, agents, evals, MCP server
web/          Next.js report interface
benchmark/    site manifest, gold labels, CI fixtures
rules/        WCAG 2.2, SEO and HTTP security rule corpus
infra/        docker-compose, images, egress limits
docs/         PLAN.md, ENGINEERING_REPORT.md
```

## Requirements

Planned: Python 3.12 with `uv`, Node 24 with `bun`, Docker and Docker Compose. Nothing is installable
yet; the commands appear in [AGENTS.md](AGENTS.md) once phase P0 creates them.

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
