# Engineering report

Numbers in this file come from stored runs under `evals/runs/` and `evals/surveys/`, and from the
audit database. Where a
number is an estimate, the sentence says so; where a claim was not measured, the section says that
instead of rounding it into existence.

## 1. What the deterministic layer does on the benchmark

Run `evals/runs/2026-11-13-baseline-chief-prompt.json`, corpus `sha256:df240161c8d3e5ea`, agent
`sha256:37d4af33aee7bb8b`, 2026-11-13, 326.3 s, whole corpus (8 synthetic sites, 104 pages, 80
planted defects, 24 clean pages):

| metric | value | denominator |
| --- | --- | --- |
| precision | 1.0000 | 80/80 |
| recall | 1.0000 | 80/80 |
| false-positive rate | 0.0000 | 0/80 |
| pages with at least one unlabelled finding | 0.0000 | 0/104 |
| duplicate rate | 0.0000 | 0/88 |
| duration | 326.3 s | 104 pages (3.14 s/page) |

Every rule scores 8/8 on its own labels. **This is a floor, not a claim about the open web.** The
generator plants exactly the defects the catalogue promises to catch, so `1.0`/`1.0` means "no
planted defect was lost and nothing was invented". A precision figure for real sites would need
labelled real sites; this corpus cannot produce one, and the README says so next to the table.

Two corrections were needed before the corpus could be trusted, and both were defects in the corpus
rather than in the agent:

- axe treats `placeholder` as an accessible name, so the field planted for `A11Y-LABEL` carried a
  name and nothing was wrong. The planted input is bare now.
- the banner planted for `LAYOUT-OCCLUSION` also had a faint text colour and a close control with no
  name, so it planted `A11Y-CONTRAST` and `A11Y-LINK-NAME` as well. Its text is legible and the
  close control is named now.

## 2. A public site: 60 pages of docs.python.org

Run `evals/surveys/2026-11-13-docs-python.json`, 2026-11-13, `sitewarrant survey
https://docs.python.org/3/ --max-pages 60 --pages-per-template 50`, deterministic layer only (no
agents, so `llm_calls: 0` and `cost_estimate_usd: 0.0`):

| metric | value |
| --- | --- |
| pages discovered | 200 |
| pages selected / audited / failed | 60 / 58 / 2 |
| findings | 19 over 17 pages (`major` 11, `minor` 8, no blocker) |
| root causes | 0 |
| observations | 2 148 |
| wall clock | 447.8 s (7.7 s per page including discovery) |
| `agent_version` | `sha256:37d4af33aee7bb8b` |

The two failures are field data, not noise to delete: one screenshot and one navigation each hit the
30 s page timeout on pages with heavy generated markup. The report says `status: partial` and the CLI
names both; a survey that dropped them quietly would read as a complete pass over 60 pages.

**Zero root causes is the interesting number.** A cause needs two findings from two categories on one
block, and on these pages the defects sit on different elements — eleven contrast failures on inline
code, one page with no `lang`, a missing meta description. Calling any of that a shared cause would be
inventing a block. On the fixture, where a banner really does cover the navigation, the same code finds
one cause with six symptoms.

What this run does not say: precision or recall. There are no labels for docs.python.org, so the claim
is only that the tool crossed 50 real pages at a polite rate and produced one auditable artifact — not
that its findings are right. The rules it fired were `A11Y-CONTRAST`, `A11Y-LANG`, `A11Y-LINK-NAME`
and `SEO-META-DESC`; seven of the ten catalogue rules stayed silent, which is also unlabelled and
therefore neither a hit nor a miss.

## 3. Two agent versions, compared

The fixture audit is the only place where two versions were run against the same page with the same
planted defects:

| version | audit | findings | blocker/major/minor | what changed |
| --- | --- | --- | --- | --- |
| `sha256:77ad5403f8fe400f` (P3) | fixture, `seo,a11y` agents | 18 | — | findings counted per evidence item; five links under the banner were one finding |
| `sha256:668a9010f1b1e6d2` (P4) | fixture, deterministic + agents | 14 | 2 / 11 / 1 | anchor-based dedupe, one root cause `header:nth-of-type(1)` covering six symptoms, `duplicate_rate` 0 |

The difference is entirely the chief layer: fewer findings, because duplicates collapsed into one
root cause, and the same ten planted defects are still covered. The comparison predates the corpus,
so it is a fixture comparison, not a benchmark comparison — the honest way to say it is "the numbers
moved the way dedupe predicted", not "the newer version is 22 % better".

A third version followed on 2026-11-13 for the Chief Auditor's narration (`sha256:7a38f0021c0d2257`),
and it is deliberately not in the table: narration changes the words that explain a cluster, not the
cluster, so on the same fixture it reports the same findings with a longer `rationale`. A model that
made findings better would show up in the benchmark; a model that only writes prose cannot.

A benchmark comparison of two agent versions is now possible without new code: run `sitewarrant eval`
twice and pass the two files to `sitewarrant prompt-check` or `sitewarrant eval --compare`. It has not
been run, because each pass over the corpus with an agent costs about forty minutes of model time.

## 4. Cost

The deterministic layer costs nothing: no model call is made when `--agents` is absent, and the
report says `llm_calls: 0`, `cost_estimate_usd: 0.0`.

Amounts are priced from `pricing/pricing.yaml` (version `2026-11-13`, OpenCode Console list price:
$0.30 per 1M input tokens, $1.20 per 1M output). The project runs on the Zen Go plan, which bills a
subscription: the number is what these tokens would cost at list price, never an invoice line. The
report carries that sentence in `summary.pricing.basis`.

Measured on the fixture page with `--agents seo,a11y` (2026-11-13, one page, three viewports,
`agent_version sha256:668a9010f1b1e6d2`, trace `641332b1bfc4c8f8b99bc1e63cbee5b0`):

| agent | status | model | findings | llm calls | tokens in | tokens out | cost, USD (estimate) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| seo | ok | deepseek-v4.1-flash | 3 | 3 | 22 878 | 4 474 | 0.012232 |
| a11y | ok | deepseek-v4.1-flash | 8 | 5 | 50 306 | 7 943 | 0.024622 |
| **total** | completed | — | **25** (2 blocker, 19 major, 4 minor) | 8 | 73 184 | 12 417 | **0.036854** |

The same page without agents yields 14 findings and `llm_calls: 0`, `cost_estimate_usd: 0.0`: the
deterministic layer is free, and every finding it loses by adding agents would be a finding the
facts already proved.

The Chief Auditor's explanation is a ninth model call, and it is billed like the others but costs a
fraction of them. On the same fixture page with `--agents a11y` and narration on (2026-11-13, trace
`9fb6130d`), the summary carries a `chief` row: 1 call, 1 010 tokens in, 1 032 out, `$0.001541`
estimated, status `ok`, alongside the accessibility agent's 7 calls and `$0.031105`. The paragraph it
produced names the six findings in the header and says which of them a screen reader user loses —
and every number in it was checked against the cluster's facts before it was kept.

At list price this is **$3.69 per 100 pages** (`0.036854 × 100`), or about 16.5 minutes of wall time
per page on this machine (135 s for the fixture page including three viewports and both agents). The
ceiling `SITEWARRANT_AUDIT_COST_LIMIT_USD` defaults to `0.25` per audit, roughly seven pages of this
profile, which is why a crawler run of 50+ pages needs the ceiling raised deliberately rather than
discovered at the invoice.

## 5. Traces

The fixture audit above records one trace holding `audit: 1, page: 3, agent: 2, llm.call: 8,
tool.call: 8` spans. Nesting is checked in `tests/integration/test_observability.py`: the page and
agent spans are children of the audit span, and every model call is a child of its agent, because the
span context — not a hand-passed parent — decides. `audits/<id>/trace.jsonl` holds the same records
as JSON lines, each carrying the trace id that `llm_calls.trace_id` points at, so a stored cost can
be walked back to the call that produced it.

## 6. The prompt gate

`sitewarrant prompt-check --baseline old.json --candidate new.json` accepts a change only when
precision does not fall and the false-positive rate does not rise; two runs on different corpora are
refused rather than compared. It is covered by `tests/test_prompt_gate.py` (8 cases, including that a
tolerance buys measurement noise and not a regression). No prompt edit was shipped through it yet:
the gate exists, its first real decision will be the first prompt change someone proposes.

## 7. What is not measured

- Precision on real sites. The corpus is synthetic; nothing in this repository justifies a number for
  the open web.
- Retrieval quality of the rule corpus. Embeddings are deterministic hash bag-of-words, chosen for
  reproducibility; whether they retrieve the right claim was never measured against a labelled set.
- A benchmark comparison of two LLM agent versions (§2), and the cost of a full agent pass over the
  corpus.
- The public demo. `infra/demo.yml` and `api/Dockerfile` exist; the stack answers on loopback
  (`/health`, migrations, `POST /audits`) and the image builds, but no VPS or domain has been pointed
  at it, so "public URL under 15 minutes" is unverified.
- The quality of the Chief Auditor's prose. The check is arithmetic — no number outside the cluster's
  facts — not editorial: nobody has labelled a set of good explanations, so "this sentence explains
  the cause better than that one" is a judgement, not a measurement here. What is measured is that a
  sentence the check rejects never reaches the report.
- Concurrency and load. `POST /audits` starts the run as an in-process task and answers `202`, so
  the interface can follow it; there is no queue and no worker, so a restart loses a running audit
  and a burst of submissions runs several browsers. Fine for a demo, wrong for a crawler of 50 pages.
