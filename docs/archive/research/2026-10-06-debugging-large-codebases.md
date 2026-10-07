# Debugging Large Codebases with Heavy Interrelations

Date: 2026-10-06
Scope: science of debugging large interconnected codebases. Methods: delta debugging, fault localization, program slicing, bisect, observability/tracing, static analysis, mutation/property testing.
Audience: sparkforge maintainers. Goal: select practical techniques for `src/sparkforge`.

## 1. Summary

Large interconnected codebases fail at interaction points, not single lines. No single method covers all fault types. Evidence supports a layered workflow:

1. Reproduce deterministically, then minimize input with delta debugging.
2. Localize in time with version bisect (`git bisect run`).
3. Localize in space with spectra (SBFL) and slicing.
4. Confirm with static analysis (ruff, mypy, bandit) before runtime debugging.
5. Harden with property tests (Hypothesis) and mutation score, not line coverage alone.
6. Instrument long-lived systems with OpenTelemetry traces/metrics/logs.

Each section below gives definition, primary source, when to use, limits, and sparkforge mapping.

## 2. Delta debugging (ddmin)

Definition: automated minimization of failure-inducing input to a 1-minimal case where removing any single entity removes the failure. Also isolates passing/failing difference pairs.

Primary sources:

- Zeller and Hildebrandt, "Simplifying and Isolating Failure-Inducing Input," IEEE Trans. Software Eng. 28(2), 2002. DOI: https://doi.org/10.1109/32.988498 — Mozilla case: 95 user actions reduced to 3; 896 HTML lines reduced to 1 line; 139 automated runs.
- Zeller and Hildebrandt, "Simplifying and Isolating Failure-Inducing Input: A Retrospective on Delta Debugging," IEEE Trans. Software Eng. 2025. DOI: https://doi.org/10.1109/TSE.2025.3537167 — origins, impact, future directions including LLM-integrated systems.

Algorithm: `ddmin` partitions input into n subsets, tests complements and subsets, increases granularity on failure to resolve. Worst case quadratic in test runs; works when test is automated and deterministic. Hierarchical delta debugging (HDD) extends this to trees (ASTs, JSON configs).

Use when: large repro input, flaky-looking harness failure with big context dump, agent task-graph payload suspected of containing irrelevant fields.

Limits: needs fast automated oracle (pass/fail). Non-deterministic failures need metamorphic or statistical oracle. Recent work (DDMT, 2026) addresses oracle-free reduction via metamorphic testing.

Sparkforge mapping: minimize failing `forge.py` / `orchestration.py` job payloads before reading code. Keep a `repro.sh` returning exit 0/1.

## 3. Spectrum-based fault localization (SBFL)

Definition: rank program elements by suspiciousness from pass/fail execution spectra. Core formulas: Tarantula, Ochiai, Jaccard, AMPLE, Barinel, DStar, OP.

Primary sources:

- Jones et al., Tarantula (ICSE 2002 / TSE 2005): first widely cited spectrum visualization and ranking.
- Abreu, Zoeteweij, van Gemund, "An Evaluation of Similarity Coefficients for Software Fault Localization," PRDC 2006. DOI: https://doi.org/10.1109/PRDC.2006.18 — Ochiai outperforms Tarantula/AMPLE/Pinpoint on Siemens suite; ~5% average code-inspection saving, up to 30% in specific cases.
- Le, Thung, Lo, "Theory and practice, do they match? A case with spectrum-based fault localization," ICSM 2013. DOI: https://doi.org/10.1109/ICSM.2013.52 — theoretically optimal formulas under Xie et al. assumptions do not beat Ochiai/Tarantula empirically when assumptions break.
- Widyasari et al., "Real world projects, real faults: Evaluating SBFL techniques on Python projects," Empir. Softw. Eng. 27(6), 2022. DOI: https://doi.org/10.1007/s10664-022-10189-4 — on BugsInPy real Python faults: older Tarantula/Barinel/Ochiai beat newer OP/DStar; Python real faults harder than Defects4J Java faults; combining techniques helps.

Use when: test suite exists with at least one failing and several passing tests. Collect coverage per test (`coverage.py`, `pytest-cov`), compute Ochiai as default ranker.

Limits: single-fault assumption weak on interacting faults. Needs good test diversity. Scores mislead on omission faults (missing code never executed). Treat ranking as inspection order, not proof.

Sparkforge mapping: add `pytest --cov=src/sparkforge` spectra to failing modules first; inspect top-10 Ochiai lines before slicing.

## 4. Program slicing

Definition: subset of statements affecting a slicing criterion `<point, variables>`. Backward static slice: what can affect value. Forward slice: what is affected. Dynamic slice: same for one concrete execution trace. Executable slice preserves runnable behavior.

Primary sources:

- Weiser, "Program Slicing," IEEE Trans. Software Eng. SE-10(4), 1984 (thesis 1979; ICSE 1981). Foundational definition.
- Binkley and Gallagher, "Program Slicing: A Survey," Adv. Comput. 43, 1996 — taxonomy: static/backward/forward, dynamic (Korel-Laski), interprocedural via program/system dependence graphs (Horwitz-Reps-Binkley).
- Gallagher and Kozaitis, "Program Slicing: A Brief Retrospective," IEEE Trans. Software Eng. 51(3), 2025. DOI: https://doi.org/10.1109/TSE.2025.3538279 — static vs dynamic trade-off: static broad but noisy; dynamic precise but input-specific.
- Kent lecture notes on static analysis (Weiser 82 formulation): criterion `<line, variable>`, PDG traversal. Useful operational summary.

Use when: heavy interrelations make grep useless. Backward-slice from wrong variable at failure point; forward-slice from suspect config flag.

Limits: static slices explode on dynamic Python (aliases, decorators, plugins). Prefer dynamic slices from actual failing trace, or LLM-assisted slicing with dataflow constraints (e.g., SLICEFORMER, ACL 2026) with human verification.

Sparkforge mapping: for cross-module faults (`routing.py` -> `providers.py` -> `agents.py`), slice on failing return value rather than reading whole chain.

## 5. Version bisect

Definition: binary search over ordered commit history to find first commit changing a property. `O(log N)` test runs.

Primary source:

- Git official documentation: `git-bisect`. https://git-scm.com/docs/git-bisect — `start`, `good`/`bad` (or `old`/`new`), `skip`, `run <cmd>`, `reset`, `replay`, `visualize`. Exit-code contract for `bisect run`: 0 = good, 1-124 except 125 = bad, 125 = skip.

Use when: "worked yesterday" regressions. Fully automate: `git bisect start HEAD v1.0 -- src/sparkforge && git bisect run pytest tests/test_x.py`.

Limits: needs linearizable history and reliable oracle. Flaky tests cause wrong bisection; use `skip` on unbuildable commits. Non-monotonic faults (fixed then rebroken) violate binary-search assumption.

Sparkforge mapping: gate every bisect with one deterministic test file, narrow path to suspect subsystem.

## 6. Observability and tracing

Definition: three stable signals — traces (request path as spans), metrics (aggregates), logs (events) — plus baggage and emerging profiles. Correlate by trace/span IDs.

Primary sources:

- OpenTelemetry specification and docs: https://opentelemetry.io/docs/ — vendor-neutral APIs, SDKs, Collector (receivers/processors/exporters), OTLP wire protocol. Merger of OpenTracing + OpenCensus (2019). CNCF graduated May 2026; profiles in alpha.
- CNCF survey context 2025: observability gaps top operational challenge for microservices; async boundaries (queues, event buses) need manual context propagation.

Use when: fault spans processes, threads, agents, MCP servers. Instrument once with OTel SDK; route via Collector to Jaeger/Tempo (traces), Prometheus (metrics), Loki/ELK (logs). `src/sparkforge/otel_tracing.py` already exists — verify it propagates context across `orchestration.py` and `mcp_client.py`.

Limits: tracing shows where time/errors go, not why logic is wrong. Sampling hides rare faults. High-cardinality attributes explode cost.

Sparkforge mapping: trace job ID end-to-end (API -> router -> provider -> tool -> MCP). Assert span error status in heldout verifier gate.

## 7. Static analysis (ruff, mypy, bandit)

Definition: find bug classes without execution. Linter (style/logic), type checker (contract violations), security scanner (AST pattern match).

Primary sources:

- Ruff docs: https://docs.astral.sh/ruff/ — Rust linter/formatter, Flake8/isort/Black/pyupgrade replacement, 900+ rules, `ruff check` + `ruff format`, `pyproject.toml` config.
- mypy docs: https://mypy.readthedocs.io/ and https://mypy-lang.org/ — gradual typing, `--strict`, stubs, `# type: ignore[code]` discipline.
- Bandit docs: https://bandit.readthedocs.io/ — AST plugins for Python security issues, severity/confidence levels, JSON/SARIF output, `# nosec` with test IDs, baseline mode (`-b`) for focusing on new findings.
- Real Python tool references for Bandit/mypy give concise install/config/usage summaries.

Use when: always, as cheapest gate. Order: `ruff check`, `ruff format --check`, `mypy`, `bandit -r`.

Limits: false positives; type-ignores rot; security scanners miss logic flaws. Never treat clean static run as correctness proof.

Sparkforge mapping: this session runs all three on `src/sparkforge` (see section 9 and HANDOFF).

## 8. Mutation testing and property-based testing

Definitions: mutation testing seeds small faults (mutants); mutation score = killed / non-equivalent total. Measures test sensitivity, not just reachability. Property testing states invariants over all inputs; framework generates inputs and shrinks minimal counterexample.

Primary sources:

- Jia and Harman, "An Analysis and Survey of the Development of Mutation Testing," IEEE Trans. Software Eng. 37(5), 2011. DOI: https://doi.org/10.1109/TSE.2010.62 — standard survey; equivalent-mutant problem; competent-programmer and coupling-effect hypotheses.
- Claessen and Hughes, "QuickCheck: A Lightweight Tool for Random Testing of Haskell Programs," ICFP 2000 — origin of property-based testing; most-cited ICFP paper; generator + property + shrink loop.
- Hypothesis docs: https://hypothesis.readthedocs.io/ — Python `st.*` strategies, `@given`, integrated shrinking on byte stream (preserves generator invariants better than type-directed shrinking), stateful/model-based testing.
- Shi et al., "Etna: An Evaluation Platform for Property-Based Testing," Proc. ACM Program. Lang. (ICFP) 2023. DOI: https://doi.org/10.1145/3607860 — coverage alone misleads (citing Gopinath et al. 2014; Klees et al. 2018); mutation testing as better effectiveness metric for PBT comparison.

Use when: coverage high but bugs escape. Write roundtrip, idempotence, metamorphic, and invariant properties for parsers, schedulers, routers. Example: `sorted(xs)` ordered + length-preserving; serialize/deserialize roundtrip.

Limits: mutation testing costly (build x tests x mutants); needs mutant sampling and selection. Property testing needs good generators; bad generators give false confidence. Shrinking essential — unshrunk counterexample undebuggable.

Sparkforge mapping: property-test `taskgraph.py` topological invariants, `routing.py` provider-selection invariants, config roundtrips. Track mutation score on those modules, not global coverage.

## 9. Recommended workflow for sparkforge

1. Write deterministic repro (`pytest` file, exit code contract).
2. `git bisect run` for regression window.
3. Minimize repro input (manual ddmin or `pytest --collect-only` trim).
4. SBFL rank with Ochiai from coverage spectra.
5. Slice backward from failure point; forward from suspect flag.
6. Fix, then add property test + regression test.
7. Gates: `ruff`, `mypy --strict` on touched files, `bandit` baseline diff.
8. If cross-service: check OTel trace for span where error first appears.
9. Record incident in `.agent/README-<domain>.md` + `.agent/HANDOFF.md` same session.

## 10. Sources cited

- IEEE TSE 2002 Zeller/Hildebrandt delta debugging. DOI: https://doi.org/10.1109/32.988498
- IEEE TSE 2025 retrospective delta debugging. DOI: https://doi.org/10.1109/TSE.2025.3537167
- PRDC 2006 Abreu et al. Ochiai SBFL. DOI: https://doi.org/10.1109/PRDC.2006.18
- ICSM 2013 Le et al. theory vs practice SBFL. DOI: https://doi.org/10.1109/ICSM.2013.52
- Empir. Softw. Eng. 2022 Widyasari et al. SBFL on Python. DOI: https://doi.org/10.1007/s10664-022-10189-4
- Weiser 1984 Program Slicing; Binkley-Gallagher 1996 survey; Gallagher-Kozaitis TSE 2025 retrospective. DOI: https://doi.org/10.1109/TSE.2025.3538279
- Git bisect official docs. https://git-scm.com/docs/git-bisect
- OpenTelemetry docs/spec. https://opentelemetry.io/docs/
- Ruff docs. https://docs.astral.sh/ruff/
- mypy docs. https://mypy.readthedocs.io/
- Bandit docs. https://bandit.readthedocs.io/
- Jia-Harman 2011 mutation survey. DOI: https://doi.org/10.1109/TSE.2010.62
- Claessen-Hughes 2000 QuickCheck ICFP.
- Hypothesis docs. https://hypothesis.readthedocs.io/
- Shi et al. Etna 2023. DOI: https://doi.org/10.1145/3607860
