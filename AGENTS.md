# AGENTS.md

Working agreement for this repository. It covers how to run things, what must not break, and which
mistakes have already been made on paper so they are not made in code.

[docs/PLAN.md](docs/PLAN.md) is authoritative on product scope, metrics and phase order. If this file
disagrees with the plan, the plan is right — fix this file in the same change.

## Status

**Phase P0 is complete.** The repository holds a working vertical slice: one page in, one JSON report
out, every finding citing a stored observation. `api/` has the FastAPI service, the Playwright capture,
axe-core, the DOM probe and the rule engine; `web/` is a Next.js page that renders a stored report;
`infra/` brings up Postgres, Redis and a fixture site with nine planted defects.

The commands below were executed at least once on 2026-11-12 and are annotated with the phase that
makes them meaningful. Anything marked with a later phase does not work yet — do not present it as
working, and do not add a command to this file that has not been run.

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

Verified P0 commands, plus the ones that only work once their phase lands. Phase in brackets says when
each becomes real; `verified` means it ran against this repository.

```bash
# Infrastructure [P0, verified]
docker compose -f infra/docker-compose.yml up -d --wait   # ports bound to 127.0.0.1

# Backend [P0, verified]
cd api && uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest -q -m "not integration and not network"    # unit, no network, no database
uv run pytest -q -m integration                           # database, fixture site, Chromium
uv run alembic upgrade head

# Audit [P0, verified]
uv run sitewarrant audit http://localhost:8081/ --allow-private --out report.json
uv run sitewarrant audit https://example.com --out report.json
uv run sitewarrant audit https://example.com --ignore-robots --out report.json
uv run sitewarrant version

# Not implemented yet, do not present as working
# uv run sitewarrant crawl <url> --max-pages 50 --out pages.json    [P1]
# uv run sitewarrant eval --dataset benchmark --out evals/runs/latest.json  [P5]
# uv run sitewarrant reaudit <audit_id> --against-report old.json   [P6]
# uv run sitewarrant-mcp                                            [P3]

# Frontend [P0 stub verified]
cd web && bun install
bun run dev
bun run build
bunx biome check .
bunx tsc --noEmit

# Single gate before a commit [P0, verified]
make check
```

`make check` is the contract: ruff, mypy, pytest, biome and `tsc` in one command. It runs against the
committed state of both apps; run it before claiming a change is verified.

## Review

Pull requests get an automated CodeRabbit review. [.coderabbit.yaml](.coderabbit.yaml) restates the
invariants above as review instructions; where a comment disagrees with this file or `docs/PLAN.md`,
the document wins. The configuration is read from the base branch, so it takes effect once it is on
`main`.

## Layout

What exists today:

```
api/app/api/       FastAPI app: health, create audit, fetch stored report
api/app/core/      config, database engine, ORM models, report schema, agent_version, page_key
api/app/rules/     catalog.py (what we claim) and engine.py (facts to findings)
api/app/storage/   repository functions over the ORM
api/app/tools/     axe, dom_probe, fetch (Playwright), guard (SSRF), robots; vendor/axe.min.js
api/migrations/    Alembic environment and revisions
api/tests/         unit tests and tests/integration (fixture site, database, browser)
web/app/           Next.js report page
benchmark/fixtures/  static site with planted defects, expected.json, robots.txt
infra/             docker-compose: Postgres with pgvector, Redis, fixture site
```

What later phases add: `api/app/crawl/`, `api/app/agents/`, `api/app/mcp/`, `api/app/evals/`,
`api/app/worker/`, `rules/` (the WCAG and header corpus).

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
- **Typer collapses a single-command app to the root.** With one command, `sitewarrant audit <url>` becomes
  `sitewarrant <url>` and the documented command breaks. The `version` command exists partly to keep the
  subcommand shape that `docs/PLAN.md` promises.
- **The stdlib `robotparser` does not implement longest-match precedence.** `Allow: /` before
  `Disallow: /private` allows everything, because the first matching rule wins. `app/tools/robots.py` uses
  protego and `tests/test_robots.py` pins that case; do not "simplify" it back to the stdlib.
- **`pytest-asyncio` gives each test its own event loop.** A pooled SQLAlchemy engine then hands a
  connection from a dead loop to the next test and fails with "Event loop is closed". Tests set
  `SITEWARRANT_DB_NULL_POOL=1`; do not remove it to make tests "faster".
- **Playwright must run against a Chromium that exists.** `uv run playwright install chromium` is a
  separate step from `uv sync`, and CI does it explicitly.
- **Alembic autogenerate omits the `postgresql` import for JSONB columns.** The generated revision fails
  with `NameError` until the template renders `${imports}` (it now does) or the import is added by hand.
- **Playwright's route handler never sees a redirect hop.** The browser follows a redirect without calling
  the handler again, so `context.route` cannot guard redirects; CDP `Fetch.requestPaused` fires for each
  hop. `tests/integration/test_guard_redirects.py` pins the difference — do not "simplify" the guard back
  to `context.route`.
- **`add_script_tag` fails under a strict CSP.** Inject axe through `Runtime.evaluate` instead; the
  `csp.html` fixture fails if anyone switches it back.
- **Private access is an allowlist of hosts, not a boolean.** `SITEWARRANT_ALLOW_PRIVATE_HOSTS` names the
  hosts that may resolve to private addresses, so auditing the local fixture does not also permit a
  redirect to a cloud metadata address.
- **The initial migration refuses a silent downgrade.** It drops every table, so it raises unless
  `SITEWARRANT_ALLOW_DESTRUCTIVE_DOWNGRADE=1` is set. That is deliberate; do not remove the guard to
  make a reset script shorter.

## Where decisions live

| Question | Document |
| --- | --- |
| What is built, in what order, how it is measured | [docs/PLAN.md](docs/PLAN.md) |
| How to work here, what not to break | this file |
| Why the project exists and what it should feel like | [idea.md](idea.md) |
| Why the name is SiteWarrant | [.agents/plans/2026-11-12-naming.md](.agents/plans/2026-11-12-naming.md) |

Open questions are listed in `docs/PLAN.md` section 17. Do not answer them silently inside a change:
either the owner answers with item numbers, or the change stays inside the stated assumption.
