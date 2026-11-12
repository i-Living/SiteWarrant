# AGENTS.md

Working agreement for this repository. It covers how to run things, what must not break, and which
mistakes have already been made on paper so they are not made in code.

[docs/PLAN.md](docs/PLAN.md) is authoritative on product scope, metrics and phase order. If this file
disagrees with the plan, the plan is right — fix this file in the same change.

## Status

**No code yet.** The repository currently holds the specification set only: this file,
[README.md](README.md), [docs/PLAN.md](docs/PLAN.md), the original concept in [idea.md](idea.md) and the
naming decision in [.agents/plans/2026-11-12-naming.md](.agents/plans/2026-11-12-naming.md).

The commands below are targets taken from `docs/PLAN.md` section 9. They become real in phase P0, which
creates `api/`, `web/` and `infra/`. Until then, do not present them as working, and do not add a command
to this file that has not been executed at least once.

## Invariants

These are not style preferences. Breaking one silently invalidates the published metrics.

1. **Tools compute facts; the model interprets them.** Contrast ratios, header values, timings, overflow
   and touch-target sizes come from code. An agent that asserts a number not present in `observations`
   is producing a defect, not a finding.
2. **No evidence, no finding.** Every finding references at least one `observations` row from the same
   audit. The validator rejects the rest; it is not a warning.
3. **Root causes are clustered deterministically.** The cluster key is built from shared layout
   component, shared DOM ancestor and rule family. The model writes rationale and impact only. A cluster
   is a root cause only if its symptoms span at least two categories.
4. **`agent_version` is a hash.** sha256 over prompts, rule corpus, model identifiers and tool config.
   Changing a prompt creates a new version; every audit and eval run records it.
5. **Numbers carry their basis.** Any published figure comes from a run artifact under `evals/runs/`
   with a denominator and a date. A zero denominator yields `null`, not `0`. Cost is labelled an
   estimate; tokens and call counts are measured.

## Commands

Targets, not verified commands. Phase in brackets says when each becomes real.

```bash
# Infrastructure [P0]
docker compose -f infra/docker-compose.yml up -d postgres redis fixtures

# Backend [P0]
cd api && uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest -q                      # unit and integration on fixtures, no network
uv run pytest -q -m network           # real network, local only
uv run alembic upgrade head

# Audit [P0, agents added in P3]
uv run sitewarrant audit https://example.com --max-pages 50 --out report.json
uv run sitewarrant audit http://localhost:8080 --no-llm
uv run sitewarrant crawl https://example.com --max-pages 50 --out pages.json

# Evals [P5] and re-audit [P6]
uv run sitewarrant eval --dataset benchmark --out evals/runs/latest.json
uv run sitewarrant reaudit <audit_id> --against-report old.json

# MCP server [P3]
uv run sitewarrant-mcp

# Frontend [P0 skeleton, P4 report]
cd web && bun install && bun run dev
bun run build
bunx biome check src
bunx tsc --noEmit

# Single gate before a commit [P0]
make check
```

`make check` is the contract: ruff, mypy, pytest, biome and `tsc` in one command. If it does not exist
yet, do not claim a change is verified.

## Layout

```
api/app/api/       HTTP routes: create audit, status, report, feedback
api/app/core/      config, database, tracing, price table
api/app/crawl/     crawler, discovery, page-template clustering
api/app/tools/     http_probe, dom_probe, axe, lighthouse, screenshot, occlusion, responsive
api/app/agents/    eight auditors, chief auditor, prompts as separate files
api/app/mcp/       MCP server and the orchestrator's MCP client
api/app/evals/     matching, metrics, benchmark runner
api/app/worker/    Redis queue, Playwright worker
web/               Next.js report interface
benchmark/         site manifest, gold labels, CI fixtures
rules/             WCAG 2.2, SEO and HTTP security corpus plus the indexing script
infra/             compose, images, egress limits
```

## Code conventions

- **Python 3.12.** Functional style: data in and out as pydantic models, logic in small functions.
  Classes only where a framework or protocol demands them. No `Manager`, `Helper`, `Processor`, `Util`.
- **TypeScript.** Next.js app router, function components, named exports. No classes. Universal names
  from the domain, not from the framework.
- **Prompts are code.** English, one file per agent under `api/app/agents/prompts/`, reviewed like code,
  versioned through `agent_version`.
- **Names are domain names.** `observation`, `finding`, `root_cause`, `page_key`, `severity` mean exactly
  what `docs/PLAN.md` section 3 says. Do not introduce a second word for the same thing.
- **Formatting** is not a discussion: ruff for Python, biome for TypeScript. Never hand-format.

## Boundaries

**Always**

- Run `make check` before a commit and paste the real result when reporting.
- Add a fixture expectation in `benchmark/fixtures/expected.json` whenever a rule is added or changed.
- Keep every evidence reference resolvable after a change; a broken reference is a broken finding.
- Update `docs/PLAN.md` in the same change when a decision or scope changes, then this file if commands
  or invariants moved.
- Respect `robots.txt` and the SSRF guard while crawling, including in tests.

**Ask first**

- Adding a dependency, especially anything that pulls a browser, a vector store or a queue.
- Changing the database schema or a migration already applied.
- Changing eval thresholds, the matching rule, or what counts as a gold label.
- Changing default crawl limits, concurrency or egress rules.
- Adding a fifth severity level or a ninth audit direction.

**Never**

- Commit secrets, API keys, `.env` files or captured customer pages.
- Disable the SSRF guard, redirect re-validation or response size caps "just for this site".
- Make CI depend on a third-party website; CI runs against the local fixture site only.
- Delete, skip or weaken a test to make a change pass. Show the failure and ask.
- Publish a metric without its run artifact, denominator and date.
- Let an agent fabricate evidence. If a finding lacks an observation, the finding is dropped, not patched.

## Pitfalls

- **Network tests flake.** Third-party sites change hourly. CI uses the fixture site; the real benchmark
  runs nightly and is not a merge gate.
- **Lighthouse is noisy on a VPS.** Take the median of three runs, never a single number. Performance
  figures stay out of CI gates.
- **INP cannot be measured in a lab.** Use TBT as a proxy and say so in the report. Do not label TBT as INP.
- **Duplicate findings are expected from agents.** Collapse them in the chief auditor, never suppress them
  inside an agent — silent suppression hides the recall loss.
- **Flat LLM tariffs have no per-run bill.** Keep tokens, calls and wall time as the measured basis and
  label the dollar figure as an estimate from the versioned price table.
- **`page_key` normalisation decides the metrics.** Drop query and hash, strip the trailing slash. A change
  here silently changes precision and recall, so it is an "ask first" change.
- **Raw `|` inside a code span breaks a Markdown table.** Escape it or write the expression without pipes;
  the documentation checker will flag it.
- **The benchmark is only as good as its labels.** Four severities with written definitions, one matching
  rule, and a weekly re-read. Disagreements go into the label note instead of being averaged away.
- **Scope is the real risk, not difficulty.** Eight directions plus evals in eighty hours is tight. If time
  runs out, cut P6 (fix diffs), never P5 (evals) — a platform without measured quality is a demo.

## Where decisions live

| Question | Document |
| --- | --- |
| What is built, in what order, how it is measured | [docs/PLAN.md](docs/PLAN.md) |
| How to work here, what not to break | this file |
| Why the project exists and what it should feel like | [idea.md](idea.md) |
| Why the name is SiteWarrant | [.agents/plans/2026-11-12-naming.md](.agents/plans/2026-11-12-naming.md) |

Open questions are listed in `docs/PLAN.md` section 17. Do not answer them silently inside a change:
either the owner answers with item numbers, or the change stays inside the stated assumption.
