"""Minimal CLI. See master brief §68 (Phase 1 spike scope: no frontend, CLI only)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from baselines.always_escalate.agent import AlwaysEscalateAgent
from baselines.always_idle.agent import AlwaysIdleAgent
from baselines.mpc_lookahead.agent import MpcLookaheadAgent
from baselines.rule_based.agent import RuleBasedAgent
from baselines.seeded_failures.always_max_generation import AlwaysMaxGenerationAgent
from baselines.seeded_failures.ignore_reserve_margin import IgnoreReserveMarginAgent
from baselines.seeded_failures.ignore_thermal_limit import IgnoreThermalLimitAgent
from baselines.seeded_failures.never_escalate import NeverEscalateAgent
from baselines.seeded_failures.prompt_injection_victim import PromptInjectionVictimAgent
from baselines.seeded_failures.revenue_first_constraint_ignoring import RevenueFirstConstraintIgnoringAgent
from baselines.seeded_failures.trust_all_telemetry import TrustAllTelemetryAgent
from baselines.seeded_failures.trust_forecast_over_actual import TrustForecastOverActualAgent
from gridactionbench.core.decision_record import JsonlWriter
from gridactionbench.core.episode import run_episode
from gridactionbench.core.scenario import load_scenario_dir
from gridactionbench.core.trajectory_record import TrajectoryJsonlWriter, build_trajectory_record_from_episode
from gridactionbench.holdouts.generate import DEFAULT_OUTPUT_DIR, generate_holdouts
from gridactionbench.holdouts.private_seed import PrivateSeedNotConfigured, resolve_private_seed
from gridactionbench.reporting.report import build_report, render_text
from gridactionbench.runners.single_step import run_single_step
from gridactionbench.scenarios.generator import TEMPLATES, coverage_report, generate
from gridactionbench.scenarios.gb_bess.episodes import EPISODES

app = typer.Typer(help="GridActionBench CLI")

AGENTS = {
    "always-idle": lambda dt_hours: AlwaysIdleAgent(),
    "always-escalate": lambda dt_hours: AlwaysEscalateAgent(),
    "rule-based": lambda dt_hours: RuleBasedAgent(dt_hours=dt_hours),
    "mpc-lookahead": lambda dt_hours: MpcLookaheadAgent(dt_hours=dt_hours),
    "always-max-generation": lambda dt_hours: AlwaysMaxGenerationAgent(),
    "ignore-thermal-limit": lambda dt_hours: IgnoreThermalLimitAgent(dt_hours=dt_hours),
    "ignore-reserve-margin": lambda dt_hours: IgnoreReserveMarginAgent(dt_hours=dt_hours),
    "revenue-first-constraint-ignoring": lambda dt_hours: RevenueFirstConstraintIgnoringAgent(dt_hours=dt_hours),
    "trust-all-telemetry": lambda dt_hours: TrustAllTelemetryAgent(dt_hours=dt_hours),
    "never-escalate": lambda dt_hours: NeverEscalateAgent(dt_hours=dt_hours),
    "prompt-injection-victim": lambda dt_hours: PromptInjectionVictimAgent(dt_hours=dt_hours),
    "trust-forecast-over-actual": lambda dt_hours: TrustForecastOverActualAgent(dt_hours=dt_hours),
}


@app.command()
def run(
    scenario_dir: Path = typer.Argument(..., help="Directory of scenario YAML files"),
    agent: str = typer.Option("rule-based", help=f"One of: {', '.join(AGENTS)}"),
    dt_hours: float = typer.Option(0.5, help="Simulator timestep in hours (SPECIFICATION.md §9.6)"),
    output: Optional[Path] = typer.Option(None, help="JSONL output path for Decision Records"),
) -> None:
    """Run every scenario in SCENARIO_DIR against AGENT and print a per-dimension report."""
    if agent not in AGENTS:
        typer.echo(f"Unknown agent '{agent}'. Choose from: {', '.join(AGENTS)}")
        raise typer.Exit(code=1)

    scenarios = load_scenario_dir(scenario_dir)
    agent_instance = AGENTS[agent](dt_hours)

    records = []
    writer = JsonlWriter(output) if output else None
    for scenario in scenarios:
        record = run_single_step(scenario, agent_instance, dt_hours)
        records.append(record)
        if writer:
            writer.write(record)

    report = build_report(records)
    typer.echo(f"Agent: {agent}  |  Scenarios: {len(records)}  |  dt_hours: {dt_hours}")
    typer.echo("")
    typer.echo(render_text(report))


@app.command("list-scenarios")
def list_scenarios(scenario_dir: Path = typer.Argument(...)) -> None:
    """List every scenario in SCENARIO_DIR."""
    for scenario in load_scenario_dir(scenario_dir):
        typer.echo(f"{scenario.scenario_id}  [{scenario.family}]  review_status={scenario.review_status}")


@app.command("run-generated")
def run_generated(
    agent: str = typer.Option("rule-based", help=f"One of: {', '.join(AGENTS)}"),
    dt_hours: float = typer.Option(0.5, help="Simulator timestep in hours (SPECIFICATION.md §9.6)"),
    n_per_template: int = typer.Option(15, help="Instances generated per template"),
    seed: int = typer.Option(42, help="Generator seed — deterministic given (n_per_template, seed)"),
    output: Optional[Path] = typer.Option(None, help="JSONL output path for Decision Records"),
) -> None:
    """Run AGENT against the parameterised generated scenario set
    (gridactionbench/scenarios/generator.py) and print a per-dimension report."""
    if agent not in AGENTS:
        typer.echo(f"Unknown agent '{agent}'. Choose from: {', '.join(AGENTS)}")
        raise typer.Exit(code=1)

    scenarios = generate(n_per_template=n_per_template, seed=seed)
    agent_instance = AGENTS[agent](dt_hours)

    records = []
    writer = JsonlWriter(output) if output else None
    for scenario in scenarios:
        record = run_single_step(scenario, agent_instance, dt_hours)
        records.append(record)
        if writer:
            writer.write(record)

    report = build_report(records)
    typer.echo(
        f"Agent: {agent}  |  Templates: {len(TEMPLATES)}  |  Scenarios: {len(records)}  |  dt_hours: {dt_hours}  |  seed: {seed}"
    )
    typer.echo("")
    typer.echo(render_text(report))


@app.command("coverage")
def coverage() -> None:
    """Print the scenario-template coverage report (master brief §53's coverage dimensions)."""
    report = coverage_report()
    typer.echo(f"{len(TEMPLATES)} templates across {len({t.family for t in TEMPLATES})} families\n")
    for dimension, tags in sorted(report.items()):
        typer.echo(f"{dimension}:")
        for tag, count in sorted(tags.items(), key=lambda kv: -kv[1]):
            typer.echo(f"  {tag:<20s} {count}")


@app.command("run-episode")
def run_episode_cmd(
    episode_id: str = typer.Argument(..., help=f"One of: {', '.join(EPISODES)}"),
    agent: str = typer.Option("rule-based", help=f"One of: {', '.join(AGENTS)}"),
    dt_hours: float = typer.Option(0.5, help="Simulator timestep in hours (SPECIFICATION.md §9.6)"),
    output: Optional[Path] = typer.Option(None, help="JSONL output path for this run's TrajectoryRecord (docs/benchmark/TASK_MODEL.md)"),
) -> None:
    """Run AGENT through EPISODE_ID (Mode B — docs/architecture/adr/ADR-016) and report
    the per-step actions, resulting generator-output trajectory, and whether the
    episode's documented failure_signature triggered
    (docs/suites/gb-bess/SCENARIO_CATALOGUE.md)."""
    if episode_id not in EPISODES:
        typer.echo(f"Unknown episode '{episode_id}'. Choose from: {', '.join(EPISODES)}")
        raise typer.Exit(code=1)
    if agent not in AGENTS:
        typer.echo(f"Unknown agent '{agent}'. Choose from: {', '.join(AGENTS)}")
        raise typer.Exit(code=1)

    spec, check = EPISODES[episode_id]
    agent_instance = AGENTS[agent](dt_hours)
    result = run_episode(spec, agent_instance, dt_hours)

    typer.echo(f"Episode: {episode_id} ({spec.description})  |  Agent: {agent}  |  Steps: {spec.steps}\n")
    for i, record in enumerate(result.step_records):
        action = record.parsed_action.action.value if record.parsed_action else "ERROR"
        power = f" {record.parsed_action.mw:.3f}MW" if record.parsed_action and record.parsed_action.mw else ""
        proposed = None
        if record.simulator_post_state and record.parsed_action and record.parsed_action.bus_id is not None:
            proposed = record.simulator_post_state["generator_outputs_mw"].get(str(record.parsed_action.bus_id))
        proposed_str = f"{proposed:.3f}" if proposed is not None else "n/a"
        world_mw = result.world_mw_after_step[i]
        rejected = " (REJECTED - invalid, world state unchanged)" if proposed is not None and not record.hard_constraint_valid else ""
        ucv_flag = "  [UCV]" if record.ucv else ""
        typer.echo(f"  step {i}: {action}{power:<10s} -> proposed_mw={proposed_str}{rejected}  |  world_mw={world_mw:.3f}{ucv_flag}")

    signature = check(result)
    typer.echo(f"\nfailure_signature triggered: {signature.triggered}  ({signature.detail})")
    typer.echo(f"UCVs across episode: {result.ucv_count} / {spec.steps}")

    if output:
        trajectory = build_trajectory_record_from_episode(spec, result, agent_instance)
        TrajectoryJsonlWriter(output).write(trajectory)
        typer.echo(f"\nTrajectoryRecord written to {output}")


@app.command("generate-holdouts")
def generate_holdouts_cmd(
    n_per_template: int = typer.Option(5, help="Candidate instances generated per template before acceptance filtering"),
    output_dir: Path = typer.Option(DEFAULT_OUTPUT_DIR, help="Output directory — git-ignored, never committed"),
) -> None:
    """Draw candidate official holdout instances from the public generator templates using
    a private seed, filter them through the acceptance criteria, and write only the
    accepted instances plus a manifest to OUTPUT_DIR (docs/benchmark/
    PUBLIC_PRIVATE_POLICY.md). Requires a private seed: set $GRIDACTIONBENCH_PRIVATE_SEED
    or create fixtures/private_dev_only/private_seed.txt."""
    try:
        seed = resolve_private_seed()
    except PrivateSeedNotConfigured as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)

    summary = generate_holdouts(private_seed=seed, n_per_template=n_per_template, output_dir=output_dir)
    typer.echo(f"Candidates generated: {summary.candidates_generated}")
    typer.echo(f"Accepted: {summary.accepted}  |  Rejected: {summary.rejected}  |  Sensitivity-flagged: {summary.sensitivity_flagged}")
    if summary.rejection_reasons:
        typer.echo("Rejection reasons:")
        for reason, count in summary.rejection_reasons.items():
            typer.echo(f"  {count}x {reason}")
    typer.echo(f"Written to {output_dir}/ (git-ignored)")


if __name__ == "__main__":
    app()
