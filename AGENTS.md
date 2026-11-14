# AGENTS.md

Working agreement for this repository. It covers how to run things, what must not break, and which
mistakes have already been made on paper so they are not made in code.

[docs/PLAN.md](docs/PLAN.md) is authoritative on product scope, metrics and phase order. If this file
disagrees with the plan, the plan is right — fix this file in the same change.

## Status

**Phases P0–P7 have landed code; the plan is not closed.** `api/` holds the FastAPI service, the
Playwright capture, eight deterministic channels at three viewports, the rule engine, the crawler, the
MCP fact server, eight budgeted agents behind the validator, the deterministic chief layer, the eval
runner over a frozen corpus, fixes with re-audits, and traces with a versioned cost estimate. `web/`
is a Next.js interface with one page: the stored report for `/?audit=<id>`. `infra/` brings up
Postgres, Redis and a fixture site with ten planted defects, and `infra/demo.yml` runs the same code on
loopback.

Still open, and the plan says so in each case:

- a public URL for the demo stand — the route is decided (existing VPS, §17 decision 3а), the deploy
  waits on the owner's domain and DNS;
- the vision instrument — decided as one full screenshot per viewport, three in total (§17 decision
  5а), and not written, so no report claims anything about how a page looks.

The audit of a public site at 50+ pages (§16.1) is done: `evals/surveys/2026-11-13-docs-python.json`,
58 audited pages, two that timed out and stayed in the denominator as failures.

The commands below were executed at least once on 2026-11-12 or 2026-11-13 and are annotated with the
phase that makes them meaningful. Do not add a command to this file that has not been run.

## Invariants

- **Tokens are measured, money is estimated, and the report says which is which.** `tokens_in`,
  `tokens_out` and `llm_calls` come from the provider's reply; `cost_estimate_usd` comes from
  `pricing/pricing.yaml`. An unpriced model yields `None`, never `0.0`, and one unpriced agent makes
  the audit total `None` rather than quietly smaller.
- **A price version is recorded with the audit.** `audits.config.pricing_version` and
  `llm_calls.cost_estimate_usd` mean an old run keeps its old prices; re-pricing is a migration, not
  a side effect of editing a YAML file.
- **A span that fails is still recorded.** `Tracer.span` marks `status="error"` with the message and
  re-raises: a trace that only shows successes is a marketing document.
- **The cost ceiling stops agents, not audits.** `budget_exceeded` on an agent, the same status on
  agents that never started, and the deterministic findings are still reported. `_cost_limit_in`
  opens anyio's exception groups, because a ceiling hidden inside a group would be reported as
  `failed`.
- **A prompt change is accepted on precision, not on enthusiasm.** `app/eval/gate.py` gates precision
  and the false-positive rate, refuses to compare different corpora, and defaults its tolerance to
  zero.
- **Every route is closed except the login.** `web/middleware.ts` verifies an HMAC session cookie;
  only `/login` and `/auth/login` are public, and `/api/*` answers `401` without a session. The API
  binds loopback, so the Next app is the only entry point. A future share link is an explicit
  exception in the middleware, never a blanket path.

- **A benchmark number is only as good as its denominator.** `app/eval/metrics.py` keeps counts next
  to ratios, and the run file stores the label set it was measured against, so a reader can redo the
  arithmetic. A comparison across two corpora is refused: it is not a comparison.
- **The eval corpus is generated, never hand-edited.** `benchmark/generate.py --check` compares every
  byte; a hand-fixed page would make its label a lie. Its 1.0/1.0 is a floor (the generator plants
  exactly what the catalogue promises) and the README says so.
- **A fix that cannot be written is not written.** Five rules get a patch because their repair invents
  no text; `A11Y-IMG-ALT`, `A11Y-LABEL`, `A11Y-BUTTON-NAME`, `A11Y-LINK-NAME` and `A11Y-CONTRAST`
  get a recommendation and an explicit note, because a machine-made alt or link name would hide the
  defect instead of fixing it.
- **A patch is computed against the source, not the DOM.** Browsers serialise the DOM they were given,
  so a diff built from the captured HTML reorders attributes and fails to apply; `--site-dir` makes
  `fix` read the file that is actually served.
- **The Chief Auditor narrates, it does not group.** `app/chief/cluster.py` decides membership,
  anchor and priority; `app/chief/narrate.py` asks one model call for prose about those clusters and
  keeps a sentence only when every number in it is in the cluster's facts or in the text of its rule
  (the standard's constants). A rejected, failed or unreachable narration leaves the measured
  sentence: fewer words, never fewer facts, never a new finding.
- **Every new finding is a regression.** `reaudit` does not decide which new findings are acceptable;
  it lists them and exits `1`, and `diff_findings` keeps closed, remaining and new disjoint.

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

Verified commands, annotated with the phase that makes each one meaningful. `uv run` needs the `api/`
project, so the blocks run from `api/`; the `../` paths follow from that. The CLI defaults
(`benchmark/dataset.json`, `evals/runs/latest.json`) are relative to the working directory, so from
`api/` they point nowhere — pass `--dataset` and `--out` explicitly, as the commands below do.

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
uv run sitewarrant index-rules                        # corpus into Postgres (pgvector)
uv run sitewarrant audit http://localhost:8081/ --allow-private --agents a11y --out report.json

# Crawl [P1, verified]
uv run sitewarrant crawl http://localhost:8081/ --allow-private --out pages.json
uv run sitewarrant crawl https://example.com --max-pages 50 --max-depth 3 --out pages.json

# Survey [P1 + DoD §16.1, verified 2026-11-13]: crawl, audit every selected page, merge into one report
uv run sitewarrant survey https://docs.python.org/3/ --max-pages 60 --pages-per-template 50 \
  --out ../evals/surveys/2026-11-13-docs-python.json
uv run sitewarrant survey http://localhost:8081/ --allow-private --max-pages 4 --out /tmp/survey.json

# Evals [P5, verified 2026-11-13]
python3 ../benchmark/generate.py --check          # the corpus still matches its generator
uv run sitewarrant eval --dataset ../benchmark --out ../evals/runs/latest.json
uv run sitewarrant eval --dataset ../benchmark --sites northwind --out /tmp/one-site.json
uv run sitewarrant eval --dataset ../benchmark --out ../evals/runs/latest.json \
  --compare ../evals/runs/2026-11-13-baseline-corpus-bytes.json
uv run sitewarrant prompt-check --baseline ../evals/runs/base.json --candidate ../evals/runs/new.json

# Fixes and re-audit [P6, verified]
uv run sitewarrant fix <audit_id> --site-dir ../benchmark/fixtures/site --out fixes/<audit_id>
uv run sitewarrant reaudit <audit_id> --against-report old.json \
  --patch fixes/<audit_id>/fixes.patch --site-dir ../benchmark/fixtures/site

# MCP fact server [P3, verified]: there is no console script — the orchestrator spawns it over stdio
uv run python -m app.mcp.server                    # needs SITEWARRANT_MCP_AUDIT_ID, one audit per process

# Frontend [P4, verified], from api/
cd ../web && bun install
bun run dev
bun run build
bunx biome check .
bunx tsc --noEmit

# Single gate before a commit [verified]; `make check` is read from the repository root
cd .. && make check
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
api/app/crawl/     crawler (BFS, limits), links, sitemap, template clustering, crawl report, digest
api/app/survey.py  a site-level audit: crawl, audit every selected page, merge into one report
api/app/rules/     catalog.py (10 rules), engine.py (facts to findings), corpus, store (pgvector)
api/app/agents/    specs, prompts/, runner (budgeted loop), validator, orchestrator, llm client
api/app/chief/     anchor (where a finding lives), cluster (dedupe, root causes, priority) and
                   narrate (one model call explaining the clusters) with prompts/chief.md
api/app/fixes/     patch (five mechanical rules), recommend (every finding), reaudit (closed/new)
api/app/eval/      dataset (manifest and digest), metrics (denominators), runner, compare
api/app/mcp/       fact server (stdio, one audit per process) and the agent loop's MCP client
api/app/storage/   repository functions over the ORM
api/app/tools/     eight channels: http_probe, dom_probe, axe, contrast, responsive, occlusion,
                   performance, screenshot; fetch (Playwright), http_get (httpx), guard (SSRF), robots
api/app/cli.py     the `sitewarrant` commands; telemetry.py and pricing.py sit beside it
api/Dockerfile     the API image `infra/demo.yml` and CI build
api/migrations/    Alembic environment and revisions
api/tests/         unit tests (math, thresholds, merge, validator, runner on cassettes),
                   tests/agents/cassettes (recorded exchanges), tests/crawl (in-memory sites)
                   and tests/integration (fixture site, database, browser, MCP, agents, fixes, evals)
rules/             claims.jsonl: 22 claims + 12 WCAG criteria, the corpus agents may cite
web/app/           Next.js interface: sites, site pages, audit form, current audits, report, login
web/middleware.ts  session gate: every route but /login and /auth/login needs a signed cookie
benchmark/fixtures/  static site with ten planted defects, expected.json, robots.txt, sitemap.xml
benchmark/sites/     eight generated sites + their labels (never hand-edited)
benchmark/generate.py  the only writer of benchmark/sites and dataset.json; `--check` re-digests
evals/runs/          recorded eval runs; a number in the docs must name one of these files
pricing/pricing.yaml  versioned price table; the audit stores the version it was priced with
infra/             docker-compose (Postgres with pgvector, Redis, fixture site) and demo.yml
scripts/           report_screenshot.py — the CI job that captures the report page
.github/workflows/ ci.yml (gate, image build, report screenshot), eval.yml (weekly corpus run)
docs/              PLAN.md (authoritative) and ENGINEERING_REPORT.md
```

There is no `api/app/worker/`: an audit runs inside the API request and holds it until the page is
done, which is the documented residual — fine for a demo, wrong for a crawl of 50 pages.

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
- **The viewport set is configuration, not a per-site choice.** `SITEWARRANT_VIEWPORTS` defaults to
  `390x844,768x1024,1440x900`, mobile first. Discovery renders at the first entry, so the viewport
  that decides which pages are found is inside the hashed set — there is no second viewport setting. Comparing two agent versions needs identical conditions, so
  a per-site viewport would make the comparison meaningless.
- **Commit the facts before the agents run.** The MCP server is a separate process and reads only
  committed rows, so an agent started inside the audit's open transaction sees an empty audit.
  `run_audit` commits before `run_agents`; without that the agent fails with an empty audit.
- **`mcp>=2.0` is a real floor, not a preference.** `Client` is not exported from `mcp.client` in
  1.9, and the server uses `MCPServer`; the pin is what keeps a fresh install working.
- **MCP 2.x renamed things.** The server class is `MCPServer` (`mcp.server.mcpserver`), `FastMCP`
  is gone, and the tool schema field is `input_schema` on the model while OpenAI clients expect
  `inputSchema`. `app/mcp/client.py` reads both.
- **The model gateway is not a plain OpenAI endpoint.** Cloudflare answers 1010 to a request with
  no User-Agent, the Go plan requires an `x-opencode-session` header on every call, and the base URL
  is `https://opencode.ai/zen/go/v1`. `deepseek-v4.1-flash` does support tool calling.
- **Cassettes cannot contain observation ids**, because ids are generated per audit. A cassette
  writes `{{first:contrast_violation}}` and `CassetteClient` substitutes the first id of that channel
  or kind in the audit under test; a missing channel fails the call instead of inventing an id. A
  cassette is also a fixed conversation: if the loop needs one more exchange than was recorded, the
  run ends with `llm_error` naming the cassette, which is how a validator change shows up as a test
  failure instead of a silent pass.
- **Grouped numbers can carry decimals**: `1,000.50` is one token, the comma groups and the dot
  is the decimal point; `to_float` strips commas before parsing, and the claimed precision comes
  from the part after the dot.
- **Numbers in advice are allowed to be constants.** A claim's own text carries the standard's
  constants ("24 by 24 CSS pixels", "4.5:1"), so repeating one is not a measurement claim and is
  allowed anywhere in the finding. A number that is neither measured nor in the claim is rejected.
- **Both destructive downgrades ask for the flag.** The P3 one also documents how to keep the call
  log: `pg_dump --data-only --table=llm_calls` before the downgrade, restore after re-upgrade. The P3 downgrade drops `llm_calls`, which
  cannot be regenerated, so it needs `SITEWARRANT_ALLOW_DESTRUCTIVE_DOWNGRADE=1` like P0's.
- **`pages_count` becomes 1 only after a commit persisted the page.** The failure handler reports
  what is in the database, so a run that dies before the commit says 0 and one that dies after says 1.
- **Agent names are resolved before anything is written.** An unknown name raises before the
  audit row exists, so a failed audit never claims zero pages while its facts are committed.
- **The narration is one call, checked before it lands.** `app/chief/narrate.py` sends the cluster's
  facts (anchor, categories, counts, rule ids, subjects) and accepts a sentence only if no number in
  it is missing from those facts or from the rule text quoted with them — "Six findings" is checked
  as 6, and "4.5:1" is allowed because it is the standard, not a measurement of this page. The answer
  is data, not a transcript: a non-JSON reply is `unusable_reply`, an overlong sentence is rejected
  with its reason in `summary.agents[chief].error`, and both leave the deterministic text in place.
- **A cassette owns the conversation, so narration is off while one is set.** The recording is a
  fixed agent exchange; an unrecorded narration call would spend the next replay step and end the
  agent with `llm_error`. A test that wants narration stubs `app.audit.explain_causes` instead of
  recording it (`tests/integration/test_chief_audit.py`).
- **The chief prompt is in `agent_version`.** `app/chief/prompts/chief.md` is hashed by
  `compute_agent_version` next to the agent prompts, so editing the brief moves every published
  number and the eval baseline has to be re-run.
- **A survey is N audits and one report.** `app/survey.py` discovers with the crawler, runs
  `run_audit` per selected page and merges findings, causes, observations and durations into a
  report whose `pages_audited` is the number of pages that were actually audited. A page that fails
  makes the survey `partial` and is listed in the CLI output — a shorter report with no failure
  line would read like a clean site.
- **A survey does not re-cluster across pages.** `root_cause_id` already carries `page_key`, and a
  cause is a block on a page: two pages with a `header` are two causes, and merging them would
  claim one fix for two different blocks. `merge_reports` concatenates each page's causes as they
  came.
- **The template limit decides a survey's coverage.** Every page of one template counts against
  `--pages-per-template`, so a single-template site yields that many pages however high
  `--max-pages` is; a documentation site is a handful of templates and needs both raised.
- **Typer collapses a single-command app to the root.** With one command, `sitewarrant audit <url>` becomes
  `sitewarrant <url>` and the documented command breaks. The `version` command exists partly to keep the
  subcommand shape that `docs/PLAN.md` promises.
- **The stdlib `robotparser` does not implement longest-match precedence.** `Allow: /` before
  `Disallow: /private` allows everything, because the first matching rule wins. `app/tools/robots.py` uses
  protego and `tests/test_robots.py` pins that case; do not "simplify" it back to the stdlib.
- **A crawl without its start page is not a crawl.** The start URL is required: if robots.txt refuses it,
  the guard blocks it or it answers 4xx, `crawl` raises `CrawlFailed` and exits 2. Recording it as a
  skipped page would produce a report that looks like a successful run of an empty site.
- **Template clustering is deterministic on purpose.** `app/crawl/templates.py` maps ids to `*` by path
  shape, with no model call and no heuristic on link text. The cluster key reaches published metrics, so
  a change here is an "ask first" change like `page_key`.
- **Discovery never leaves the audited host.** Sitemap entries, links and redirect targets are filtered
  against the start host, and every URL passes robots.txt, the SSRF guard and the peer check before it is
  fetched. `tests/crawl/test_crawler.py` and the fixture sitemap pin both directions.
- **The agent budget is 12 tool calls, 60k tokens and 180 s**, and the loop warns at 70 % of the
  tokens: after the warning a read is refused and the only way forward is `submit_findings`. Without
  that, a thorough agent reads until the budget dies and contributes nothing. The token number is a
  warning threshold, not a hard cap: two more calls are allowed past it so the submission fits, which
  is why a real a11y run can report ~92k input tokens. The deadline is a real cap on awaited work and
  has to stay above the client's own `SITEWARRANT_LLM_TIMEOUT_S` (120 s), or it preempts it.
- **An agent's failure is the agent's, never the audit's.** Client construction, the MCP
  subprocess and the conversation all sit inside the per-agent boundary; a broken cassette or a
  missing key yields one `failed` run and a `partial` report with the deterministic findings.
- **The deadline covers awaited work.** Loading the tool schemas, each model call and each tool call
  run under `asyncio.timeout` with the time the agent has left, and a call that would start with no
  time left is a timeout instead of a 100 ms grant. A slow reply cannot end the agent after its
  budget in `ok`.
- **Accepted findings survive a rejected sibling.** A retry usually resubmits only the candidate
  that failed validation, so accepted candidates are kept across rounds; identical resubmissions
  are dropped by their text and evidence.
- **`evidence.kind` must name the channel** (`dom`, `contrast`, …) or the stored observation kind
  (`contrast_violation`); a DOM observation labelled `axe` is rejected, because the kind is copied
  into the report.
- **A subject must be a string *value* from the payload, never a field name.** `canonical` is a
  key, so it distinguishes nothing and the copies collapse; a selector or a URL does distinguish.
- **`subject` is what makes two findings on one observation distinct.** Two small targets in one
  responsive report are two findings, so the candidate carries what it is about; without a subject
  the cited evidence is the identity, and the same claim twice in one submission is one finding.
- **An excerpt is evidence, so its numbers are checked** against the observation it names — not
  against the union of everything the finding cites, and not against the claim's constants: "24 by
  24 pixels" is the rule, and a quote that contains it is a fabricated measurement.
- **A root cause is a place, not a rule family.** The anchor is read from the selectors in the cited
  observations: the raw first path segment that is not a page wrapper, positional selector included,
  because `section:nth-of-type(1)` and `section:nth-of-type(2)` are different blocks and grouping
  them invents a cause. `RootCauseOut.label` carries the readable tag name for display only. A
  finding that names its own target (the subject is one of the cited selectors) resolves its anchor
  from that target alone, because one occlusion report can hold hits from across the whole page. A finding whose evidence spans two
  blocks has no place and joins no cluster, and a group needs two findings from two categories before
  it is called a cause (docs/PLAN.md invariant 4).
- **Dedupe merges only what is the same thing.** Identity is claim + place + subject (compared as
  written: CSS selectors are case-sensitive), and without a subject the findings must share a cited
  observation. Every retained candidate is searched, not just the first one, because a block can
  hold several findings of one rule.
- **axe nodes carry `path`.** axe reports `.icon-link`, which names no place, so `run_axe` adds the
  element's full nth-of-type path in the same evaluate — the whole path, because the anchor reads the
  outermost block and a depth cap would hide it.
- **A selector is only a selector under a selector key.** `selectors_in` ignores free text that
  happens to contain ` > `, and agreement between two paths is decided on the raw segment:
  `section:nth-of-type(1)` and `section:nth-of-type(2)` are different blocks.
- **The validator is the only path from a candidate to a finding.** An agent proposes; the
  validator checks the claim exists in the corpus, the category matches, severity is not lowered,
  every cited observation belongs to this audit, the channel is allowed for that claim, and every
  number in the text is either in a cited payload, in the cited observation's viewport, or a
  constant from the claim itself. Rejected candidates go back to the
  model with reasons, which is how the loop fixes itself.
- **Prompts, the corpus and the model id are in `agent_version`.** A different brief or a
  different model is a different agent, and its numbers are not comparable with the old one.
- **A channel must report that it ran, even with nothing to report.** Each tool writes a run
  observation (`axe_run`, `contrast_run`) next to its findings. Without it, "the tool found nothing"
  and "the tool never executed" look identical in the database, and the report would score a category
  nobody measured.
- **One rule, one finding, N evidence items.** The same defect at 390, 768 and 1440 px is one claim.
  `draft_findings` merges by `rule_id` and deduplicates evidence by observation id; a per-viewport
  finding triples the report for no new information.
- **`page.add_init_script` takes source, not a function expression.** Passing `() => {...}` defines a
  function and never calls it, so the LCP/CLS/long-task observers silently never register. Wrap the
  script in `(() => { ... })()`; `app/tools/performance.py` does.
- **LCP is not in `performance.getEntriesByType`.** It only exists through a
  `PerformanceObserver({type: 'largest-contentful-paint', buffered: true})` created before the first
  paint, which is why the observer is installed as an init script before navigation.
- **Never round a value before comparing it to a threshold.** A contrast ratio of 4.496 stored as
  4.5 claims a pass WCAG does not give, and a 23.999 px target stored as 24 hides the reason it was
  reported. Keep full precision in the fact and in the comparison; round only for display.
- **Alpha is part of the colour.** `rgb()` has three channels and is opaque; only `rgba()` and the
  slash syntax carry alpha. Composite a translucent colour over its resolved backdrop before
  measuring, or the probe reports a colour the user never sees.
- **CLS is the largest session window, not the sum of shifts**, and TBT only counts long tasks after
  the first paint and before the measurement window closes. The window closes before the geometry
  probes run, because their long tasks are the auditor's work.
- **robots.txt applies to every redirect hop.** A redirect target is a URL the tool fetches;
  `http_get` takes a `hop_check` callback and `robots.robots_hop_check` is what the audit and the
  crawler pass. The browser navigation is checked for the start URL only.
- **Performance numbers are excluded from the determinism check.** TTFB, FCP, LCP, CLS and TBT move
  between runs on the same machine; `tests/integration/test_fact_layer.py` compares every other channel
  and says so. Do not "fix" the comparison by loosening it for other tools.
- **The benchmark digest covers the markup, not only the labels.** `dataset_digest` hashes each
  site's page paths, the digest of every page's rendered text, and the labels planted in them; a
  manifest carrying a digest that does not match is refused. Labels alone would let two corpora with
  identical defects in different pages be compared as one measurement. `benchmark/generate.py` and
  `app/eval/dataset.py` must hash the same text — a test pins the generator's digest against the
  loader's, so change both or neither.
- **The crawl digest is part of `agent_version`.** `app/crawl/version.py` hashes the discovery sources,
  because which pages get audited changes the report. Editing the crawler changes every version string
  and every published number — expected, not a bug.
- **Rebinding is narrowed, not closed.** The browser is launched with
  `--host-resolver-rules=MAP <host> <ip>` for the page host, and an `httpx` response whose peer address
  is private is refused (`app/tools/guard.py::peer_is_blocked`). Third-party subresources are resolved by
  the browser and are covered only by the per-request guard check, so do not claim the window is shut.
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

Decisions are listed in `docs/PLAN.md` section 17 with the date they were taken. Do not change one
inside a change: a decision moves when the owner answers with item numbers, and the change then cites
the new answer.
