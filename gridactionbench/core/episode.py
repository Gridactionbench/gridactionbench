"""Mode B — Episode evaluation. See docs/benchmark/SPECIFICATION.md §2 and
docs/architecture/adr/ADR-016-episode-architecture.md.

Per ADR-016: the episode runner is a thin loop over the existing Mode A single-step
pipeline — the controlled generator's MW output evolves across steps (each step's
resulting output becomes the next step's starting output), while every other Oracle field
follows a per-step schedule the episode itself defines. No new Scenario/Oracle/Evaluator
machinery is introduced here; this module only adds the loop and episode-level
behavioural-metric computation that has no meaning at the single-step level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from gridactionbench.agents.base import AgentAdapter
from gridactionbench.core.decision_record import DecisionRecord
from gridactionbench.core.scenario import Scenario, TaskFamilyTags
from gridactionbench.evaluators.base import Capability
from gridactionbench.runners.single_step import run_single_step

StepBuilder = Callable[[int, float], Scenario]


@dataclass
class EpisodeSpec:
    episode_id: str
    episode_version: str
    family: str
    steps: int
    initial_mw: float
    build_step: StepBuilder  # (step_index, current_generator_mw) -> Scenario for that step
    # docs/benchmark/CAPABILITY_TAXONOMY.md / docs/benchmark/STRESS_DIMENSIONS.md — added
    # September 2026 strategic realignment (docs/project/GAP_ANALYSIS.md P1), mirroring
    # ScenarioTemplate's tags (gridactionbench/scenarios/generator.py).
    primary_capability: Capability
    u_classes: tuple[str, ...]  # one or more of U0-U7, docs/benchmark/STRESS_DIMENSIONS.md
    # "Sequential" | "Operational" (docs/benchmark/TASK_MODEL.md) — added 2026-09-09 when
    # GB-BESS-EP-001/EP-002 were found, on inspection, to already have static conditions
    # (no per-step branching in their build_step) and were reclassified from Operational to
    # Sequential; EP-003 onward genuinely vary a condition mid-episode and remain
    # Operational. Required, not defaulted — which value applies is a fact about each
    # episode's own content, not a safe default to assume.
    task_mode: str
    # H proxy (STRESS_DIMENSIONS.md, "Task modes as an H proxy, not a definition"):
    # "medium" for Sequential, "high" for Operational — no longer a single value uniform
    # across every EpisodeSpec, so no longer defaulted (see task_mode above).
    autonomy_burden: str
    description: str = ""
    complexity_rung: str = "C0"  # every GB-BESS episode is C0 — one controllable generator, no other asset


@dataclass
class EpisodeResult:
    episode_id: str
    step_records: list[DecisionRecord]
    # The actual carried-forward generator MW output after each step (post hard-constraint
    # gating) — distinct from each record's own simulator_post_state.generator_outputs_mw,
    # which is the HYPOTHETICAL outcome of that step's proposed action, computed for
    # evaluation purposes regardless of validity (docs/architecture/ARCHITECTURE.md's
    # Evaluation Engine). The two only diverge when a step's action was
    # hard-constraint-invalid — exactly the case worth being unambiguous about when
    # reading episode output.
    world_mw_after_step: list[float] = None  # type: ignore[assignment]

    @property
    def any_ucv(self) -> bool:
        return any(r.ucv for r in self.step_records)

    @property
    def ucv_count(self) -> int:
        return sum(1 for r in self.step_records if r.ucv)


def run_episode(episode: EpisodeSpec, agent: AgentAdapter, dt_hours: float, run_id: str | None = None) -> EpisodeResult:
    """Runs one episode to completion, threading the controlled generator's MW output
    from each step's simulator post-state into the next step's Oracle. Every step still
    produces a complete, independent Decision Record via the same run_single_step() path
    Mode A uses — Mode B adds no second evaluation code path (ADR-016)."""
    mw = episode.initial_mw
    step_records: list[DecisionRecord] = []
    world_mw_after_step: list[float] = []
    tags = TaskFamilyTags(
        task_mode=episode.task_mode,
        primary_capability=episode.primary_capability.value,
        complexity_rung=episode.complexity_rung,
        u_classes=episode.u_classes,
        autonomy_burden=episode.autonomy_burden,
    )
    for step in range(episode.steps):
        # Tags are attached post-hoc, never inside build_step itself (docs/project/
        # GAP_ANALYSIS.md: "no change to existing ... build functions").
        scenario = episode.build_step(step, mw).model_copy(update={"task_family_tags": tags})
        record = run_single_step(
            scenario, agent, dt_hours, run_id=f"{run_id or episode.episode_id}:step{step}"
        )
        step_records.append(record)
        # Only a HARD-constraint-valid action is allowed to advance the world state —
        # docs/suites/gb-bess/SPECIFICATION.md §9.9: "the simulator only ever executes
        # valid actions." In Mode A this distinction is invisible (there is no next
        # step to protect); in Mode B it is load-bearing. Getting this wrong was a real
        # bug caught immediately by running a genuinely defective agent through an
        # episode: it drove the *hypothetical* post-state generator output outside its
        # own limits, and the first version of this loop carried that physically-impossible
        # value into the next step's Oracle regardless of validity, crashing on the next
        # step's schema validation. An invalid or errored action leaves the world state
        # unchanged — the correct real-world analogue of "the invalid action never
        # reached the simulator."
        if (
            record.hard_constraint_valid
            and record.simulator_post_state is not None
            and record.parsed_action is not None
            and record.parsed_action.bus_id is not None
        ):
            mw = record.simulator_post_state["generator_outputs_mw"][str(record.parsed_action.bus_id)]
        world_mw_after_step.append(mw)
    return EpisodeResult(episode_id=episode.episode_id, step_records=step_records, world_mw_after_step=world_mw_after_step)
