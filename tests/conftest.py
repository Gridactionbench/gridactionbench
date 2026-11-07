"""Shared pytest fixtures.

`fake_psspy` installs a `FakePsspy` test double into `sys.modules["psspy"]` for the
duration of a test, so `gridactionbench.simulators.psspy_client`'s lazy `import psspy`
resolves to the fake rather than requiring a real, licensed PSS/E installation — see
tests/fakes/fake_psspy.py for exactly what the fake does and does not model. `autouse=True`
because nearly every test in this suite runs a scenario end-to-end, which transitively
reaches the simulator.
"""

from __future__ import annotations

import sys

import pytest

from tests.fakes.fake_psspy import FakePsspy


@pytest.fixture(autouse=True)
def fake_psspy(monkeypatch: pytest.MonkeyPatch, request) -> FakePsspy | None:
    if request.node.get_closest_marker("psse"):
        return None
    fake = FakePsspy()
    monkeypatch.setitem(sys.modules, "psspy", fake)
    return fake
