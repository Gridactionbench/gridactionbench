# Public / Private Architecture Policy

**Status:** Revised — Phase 0.5. "Private evaluation infrastructure" rewritten: the `fixtures/private_dev_only/` placeholder that was previously tracked in git (a `.gitkeep` only) has been removed from version control entirely — it was a public artifact marking the existence of a "private" directory, which defeats the point. This document now specifies how a developer creates the directory locally instead. This document exists to satisfy master brief §37-39: do not arbitrarily choose a public/private split percentage; research and justify the design.

## What must stay public (master brief §37)

Specification, schemas, simulator, evaluator *definitions* (the catalogue in `docs/suites/gb-bess/EVALUATION_SPEC.md`) and their reference *implementations*, scenario taxonomy, the public development scenario set (the initial 20 + episodes in `docs/suites/gb-bess/SCENARIO_CATALOGUE.md`), representative scenario generators, baselines, scoring methodology, the CLI, methodology, limitations, the Benchmark Card, and public results.

## What may stay private

Holdout instances, unseen parameter combinations, adversarial mutations, official seeds, official evaluation/selection manifests, future evaluation scenarios, and appropriately governed private partner cases.

## Why source code stays public and holdout answers stay private

Stated plainly, since the reasoning is otherwise scattered across the sections below: **this project does not hide the rules, only the test answers.**

- **Evaluator/simulator/generator source code stays public** because the benchmark's scientific value depends on its methodology being independently auditable — a reviewer must be able to read `gridactionbench/evaluators/`, `gridactionbench/simulators/`, and `gridactionbench/scenarios/generator.py` and confirm the rules are fair, unbiased, and match what's documented, without needing access to anything private. Moving any of this to a private repository "for security" would not protect holdout answers (they are separate artifacts, not derivable from the rules) and would instead make the benchmark unauditable, which is a worse outcome than any gaming risk it could plausibly prevent.
- **Holdout instances and the private seed stay private** because they are the *answers*, not the rules: publishing them would let a submitter hand-tune against known instances rather than demonstrate the underlying capability the public specification describes. This is the only thing withheld — the generator that produces those instances, and the acceptance criteria used to accept them, are both public (`gridactionbench/holdouts/`, above).

## Why not a fixed 80/20 split

An arbitrary public/private percentage answers the wrong question. The right question, informed by this project's own prior-art review (see `docs/research/PRIOR_ART.md` §1.1, item 3), is: **can a held-out instance be regenerated on demand from a documented, published generator, rather than hand-authored and hidden?** The Trashchenkov "Power Systems Agent Benchmark" answers this by publishing *per-family deterministic generators* openly while keeping only the private seed and the specific drawn instances hidden, with published acceptance criteria (a reference solver must solve it; the evaluator must confirm feasibility; no small perturbation of the reference solution may score higher). This is a stronger anti-gaming property than a fixed split, because:

- **Contamination resistance does not depend on the split ratio.** Even a 99%-private benchmark leaks if the private 1% never rotates; even a 50%-private benchmark stays useful if the private half is continuously regenerated from a published, auditable process.
- **Statistical power** is a property of how many scenario *instances* exist per family, not of what fraction is labeled private — a published generator can produce arbitrarily many held-out instances from a small number of hand-authored families.
- **Maintenance burden** favors generator-based holdouts: hand-authoring and periodically replacing a fixed private scenario bank does not scale with the project's own contributor model (master brief §60, open contribution to scenarios).
- **Reproducibility and transparency** are best served by keeping the *generation process* public even when specific *instances* are not — a contributor or reviewer can audit "is this generator fair and unbiased" without needing to see the private instances it produces.

## GridActionBench's policy for GB-BESS v0.1

1. **The initial 20 scenarios and 8 episodes (`SCENARIO_CATALOGUE.md`) are public development scenarios.** They exist to make the benchmark's design legible and are never treated as official held-out evaluation instances.
2. **Parameterised scenario templates (Phase 3, target ≥100 templates) are published openly**, including the generation logic/ranges, as required by master brief §37 ("representative scenario generators" is explicitly a public component).
3. **Official evaluation instances are drawn from the published templates using a private seed**, held in a separate, not-publicly-committed location (see "Private evaluation infrastructure," below) — mirroring the Trashchenkov generator pattern rather than a fixed split ratio. **Implemented — 2026-09-09**: `gridactionbench/holdouts/private_seed.py::resolve_private_seed()` reads `$GRIDACTIONBENCH_PRIVATE_SEED` or `fixtures/private_dev_only/private_seed.txt` and raises, with setup instructions, rather than ever defaulting to the public generator's own seed (`gridactionbench/scenarios/generator.py`'s `seed=42`).
4. **Acceptance criteria for a generated instance to be usable as an official holdout** (adapted from the same prior art): the reference/`RuleBasedAgent` must produce a scoreable, non-degenerate outcome on it; the relevant evaluator(s) must confirm the instance's ground truth is internally consistent (e.g., a scenario's `oracle` values must not make every action simultaneously invalid, unless that is the specific point of the scenario, e.g. HUM-019); and no minor perturbation of the instance's parameters should flip its correct-action classification in an unintended way (a basic sensitivity check, not a formal proof). **Implemented — 2026-09-09**: `gridactionbench/holdouts/acceptance.py::check_acceptance()`; run end-to-end via `gridactionbench generate-holdouts` (`gridactionbench/holdouts/generate.py`), which writes only accepted instances plus a manifest to `holdouts_private/`.
5. **Holdout fairness (master brief §39):** hidden tests evaluate only capabilities documented by the public specification (`docs/benchmark/SPECIFICATION.md`, `docs/suites/gb-bess/SPECIFICATION.md`, and the scenario taxonomy in `docs/suites/gb-bess/SCENARIO_CATALOGUE.md`'s family definitions). A holdout instance from the PHY family tests boundary precision or rate limits — it never silently introduces an undocumented eighth scenario family or an evaluator not listed in `EVALUATION_SPEC.md`.

## Private evaluation infrastructure

Per master brief §66, official holdouts are not committed to the public repository's git history — not even as an empty placeholder. `.gitignore` excludes `fixtures/private_dev_only/`, `private_eval/`, and `holdouts_private/` entirely (no exception for a `.gitkeep` or any other tracked marker), so none of these directories exist in a fresh checkout and no private scenario can accidentally enter public git history through them.

### `.gitignore` is not the security boundary

`.gitignore` is a convenience that stops an *accidental* `git add -A`/commit from surfacing these paths — it is not what makes them private, and it provides no protection at all against someone who deliberately adds a file with `git add -f`, against a path not yet listed in `.gitignore`, or against material that was committed before the corresponding `.gitignore` entry existed (see the internal-review-docs history below for a real instance of exactly that). The actual boundary is that official holdout material, the private seed, official selection manifests, and private adversarial mutations are never generated into, or stored in, this repository's working tree or history at all — they belong in a genuinely separate private evaluation repository/environment with its own access control (see "Eventual private-repository architecture," below). `.gitignore` here is defense-in-depth against mistakes, not the mechanism that keeps this material private.

### Local private fixtures — how a developer creates one

These directories are never committed, so there is nothing to check out — a developer who needs one creates it locally:

```bash
mkdir -p fixtures/private_dev_only
```

Anything placed under `fixtures/private_dev_only/`, `private_eval/`, or `holdouts_private/` (each git-ignored — see `.gitignore`) stays local to that developer's checkout. This is for **interim private-instance development only** (e.g., trying out a holdout-generator design locally before Phase 3 infrastructure exists) — it is explicitly not a substitute for the separate private-evaluation repository described below, and nothing placed here should be treated as an official holdout; there is no mechanism for these local directories to be shared, synchronized, or treated as authoritative across contributors.

### Internal-only project review documents — a second, distinct private category

Separate from holdout/evaluation material above: candid internal self-assessment documents — open risks, unresolved weaknesses, gap analyses — are useful to the maintainer but not intended for the public repository. As of 2026-09-10 these are `docs/project/ASSUMPTIONS.md`, `docs/project/RISK_REGISTER.md`, `docs/project/GAP_ANALYSIS.md`, `docs/research/BENCHMARK_DESIGN_REVIEW.md`, and `docs/research/DESIGN_EVIDENCE_BASE.md`. Unlike the fixtures above, these live alongside public docs in the same directories rather than under a dedicated private subtree, so they are excluded in `.gitignore` by exact file path rather than by a directory pattern — three of the five were briefly live on the public remote before this policy existed and were removed via a history rewrite (`git filter-repo`) and force-push on 2026-09-10; the other two had never been pushed.

**Rule for adding a new one — no exceptions:** the `.gitignore` entry for a new internal-only document must be added in the *same edit* that creates the file, never created first and hidden afterward. A file-path `.gitignore` entry only protects paths it already lists; between a new internal doc's creation and its `.gitignore` entry being added, it is exposed to an accidental `git add -A`/commit/push exactly as the original three were.

### Eventual private-repository architecture

The intended architecture is a separate private repository holding `holdouts/`, `scenario_generators/` (private-seed configuration only — the generator *code* itself remains public), `adversarial_mutations/`, `evaluation_seeds/`, `submission_validation/`, and `official_run_configs/`. **As of 2026-09-23, this repository exists** (private, not publicly readable) but is empty — none of the directories above have been populated yet, no private seed has been configured in it, and no official-run protocol has been defined. Only the generator *code* half of this architecture is built, and it lives in this public repository (`gridactionbench/holdouts/`, above), not the private one. Nothing here should be read as a claim that "GridActionBench Verified" results are now possible — they are not, until the private repository is actually populated and a defined official-run protocol exists.

**A prerequisite for that protocol, added 2026-11-05:** keeping holdout *data* out of git history (this section) says nothing about what happens to that data once it's loaded into a running evaluation and shown to an *agent* — an evaluated agent with network access could still exfiltrate it, or look up an answer externally instead of reasoning over what it was given. The Agent Execution Sandbox (`docs/architecture/adr/ADR-019-agent-execution-sandbox.md`, `docs/architecture/SECURITY.md`) is the mechanism that closes that separate gap, and is a prerequisite for populating the private repository above and actually building the "Verified" tier safely — not yet a claim that either has happened.

### Safeguard against accidental commits

Because none of `fixtures/private_dev_only/`, `private_eval/`, or `holdouts_private/` are ever tracked (no `.gitkeep` exception, unlike the Phase 0 draft), `git status`/`git add -A` will never surface files under these paths for staging — a contributor cannot accidentally `git add` a private scenario file that lives there. Contributors should still run `git status` before committing (standard practice, restated here because it is the specific safeguard this section depends on) — but see the previous subsection: this is a safeguard against mistakes, not the reason the material is private.

## Result status categories (master brief §40)

- **Local Result** — participant-generated, unverified against any holdout.
- **Reproducible Submission** — participant supplies sufficient configuration, metadata, and Decision Record traces that another party could regenerate the same result from public artifacts.
- **GridActionBench Verified** — evaluated against official private holdout infrastructure under the benchmark's defined protocol. Not available for GB-BESS v0.1 at Phase 0: the private repository now exists (see "Eventual private-repository architecture," above) but is empty, with no populated holdouts, no configured private seed, and no defined official-run protocol.

Only "GridActionBench Verified" results are eligible to be described as officially verified benchmark results in any external publication. No leaderboard UI is planned for v0.1 (master brief §40).
