"""Fake `psspy` module — a test double standing in for Siemens PTI PSS/E's real Python API.

Exists so this benchmark's test suite can exercise
`gridactionbench.simulators.psspy_client`/`psse_simulator` without a licensed PSS/E
installation (see docs/architecture/adr/ADR-018-psse-power-flow-adapter.md). Implements
only the subset of `psspy`'s documented call shape that `psspy_client.py` actually calls,
with a **deliberately simplified linear solve** for the one quantity it's asked to solve,
bus voltage:

    resulting_voltage_pu(bus) = base_voltage_pu(bus) + K_VOLTAGE_PU_PER_MW * (mw_now - mw_at_case_load)

`base_voltage_pu(bus)` is the bus's true current (pre-action) observed voltage, exactly as
the Oracle declares it — the DELTA form (not an absolute `K * mw_now`) exists so that an
action which doesn't change this generator's output (e.g. IDLE, or a no-op SET_GENERATION)
reproduces the declared base voltage exactly, with no drift.

Branch loading is **not** solved by this fake at all — `psspy_client.read_branch_loadings`
computes it directly from each branch's own declared `sensitivity_mva_per_mw`, in plain
Python shared by both the real and fake code paths, so this fake doesn't implement
`brnmsc`/line-flow calls (see that function's docstring for why).

This is **not** a real power-flow solver: no Newton-Raphson iteration, no reactive power,
no losses. It exists purely to give golden tests and baseline agents a small,
exactly-predictable stand-in for the voltage solve. Scenario authors must set each
`Generator`'s `voltage_sensitivity_pu_per_mw` to `K_VOLTAGE_PU_PER_MW` below, so the
agent-visible sensitivity hint stays truthful to what this fake actually computes. A real
PSS/E install would not need, or honour, that field at all — it exists in this benchmark's
own schema only as a pre-computed-offline-study-style hint for agents (see
`gridactionbench/schemas/observation.py`), not as a `psspy` input.
"""

from __future__ import annotations

K_VOLTAGE_PU_PER_MW = 0.01


class FakePsspy:
    """Minimal fake covering exactly the `psspy` calls `psspy_client.py` makes."""

    def __init__(self) -> None:
        self._buses: dict[int, float] = {}
        self._generators_base: dict[int, float] = {}
        self._generators_now: dict[int, float] = {}
        self._solved_voltages: dict[int, float] = {}

    def psseinit(self, max_buses: int) -> int:
        self._buses.clear()
        self._generators_base.clear()
        self._generators_now.clear()
        self._solved_voltages.clear()
        return 0

    def bus_data_4(self, ibus: int, inode: int, intgar: list, realar: list) -> int:
        self._buses[ibus] = realar[1]
        return 0

    def branch_data(self, ibus: int, jbus: int, ickt: str, intgar: list, realar: list) -> int:
        return 0

    def plant_data(self, ibus: int, inode: int, intgar: list) -> int:
        return 0

    def machine_data_2(self, ibus: int, machid: str, intgar: list, realar: list) -> int:
        self._generators_base[ibus] = realar[0]
        self._generators_now[ibus] = realar[0]
        return 0

    def machine_chng_2(self, ibus: int, machid: str, intgar: list, realar: list) -> int:
        if ibus not in self._generators_now:
            return 1
        self._generators_now[ibus] = realar[0]
        return 0

    def fnsl(self, options: list) -> int:
        for bus_id, base_voltage in self._buses.items():
            delta_mw = self._generators_now.get(bus_id, 0.0) - self._generators_base.get(bus_id, 0.0)
            self._solved_voltages[bus_id] = base_voltage + K_VOLTAGE_PU_PER_MW * delta_mw
        return 0

    def busdat(self, ibus: int, field: str) -> tuple[int, float]:
        if field != "PU":
            return 1, 0.0
        return 0, self._solved_voltages.get(ibus, self._buses.get(ibus, 0.0))

    def solved(self) -> int:
        return 0

    def macdat(self, ibus: int, machid: str, field: str) -> tuple[int, float]:
        if field != "P":
            return 1, 0.0
        return 0, self._generators_now.get(ibus, 0.0)
