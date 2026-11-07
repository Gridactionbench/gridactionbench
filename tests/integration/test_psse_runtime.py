"""Compare real PSS/E against an independently checked, operator-supplied reference.

Never silently substitute the fake. No proprietary case or license is bundled.
"""
import json
import os
from pathlib import Path

import pytest

from gridactionbench.schemas.action import AgentActionV1
from gridactionbench.schemas.observation import NetworkModel
from gridactionbench.simulators.psse_simulator import PSSESimulatorAdapter

REFERENCE = os.environ.get("GRIDACTIONBENCH_PSSE_REFERENCE")
pytestmark = [pytest.mark.psse, pytest.mark.skipif(not REFERENCE, reason="requires licensed PSS/E reference JSON")]


def test_licensed_solver_against_independent_reference(record_property):
    import psspy  # No fake fixture for psse-marked tests.
    assert getattr(psspy, "__file__", None), "expected the installed PSS/E module"
    reference = json.loads(Path(REFERENCE).read_text(encoding="utf-8"))
    for name in ("psse_version", "python_version", "reference_method"):
        assert reference.get(name), f"reference must document {name}"
        record_property(name, reference[name])
    result = PSSESimulatorAdapter().step(NetworkModel(**reference["network_model"]),
        AgentActionV1(**reference["action"]), dt_hours=0.5)
    assert result.converged
    for field in ("bus_voltages_pu", "generator_outputs_mw"):
        actual = getattr(result, field)
        expected = {int(key): value for key, value in reference["expected"][field].items()}
        assert actual == pytest.approx(expected, abs=1e-6, rel=1e-6)
