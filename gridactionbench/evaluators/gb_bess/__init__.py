"""GB-BESS evaluator catalogue. See docs/suites/gb-bess/EVALUATION_SPEC.md.

evaluator_set_version: 1.0.0 — bumped 2026-11-04 for the PSS/E power-flow pivot
(docs/architecture/adr/ADR-018-psse-power-flow-adapter.md): PHY and NET evaluator logic
changed from battery/SOC formulas to voltage/thermal-limit formulas, which changes
pass/fail semantics for those evaluator IDs — a MAJOR change per
docs/benchmark/VERSIONING.md's SemVer interpretation, not an additive one.
"""

from gridactionbench.evaluators.gb_bess.data import DATA_EVALUATORS
from gridactionbench.evaluators.gb_bess.mkt import MKT_EVALUATORS
from gridactionbench.evaluators.gb_bess.net import NET_EVALUATORS
from gridactionbench.evaluators.gb_bess.ops import OPS_EVALUATORS
from gridactionbench.evaluators.gb_bess.phy import PHY_EVALUATORS

EVALUATOR_SET_VERSION = "1.0.0"

# "Standard" evaluators: fit the uniform Evaluator.evaluate(ctx) protocol. HUM and ADV are
# orchestrated separately by the Evaluation Engine (see gridactionbench.core.engine) since
# they are cross-cutting/derived, not independently computable from ctx alone.
STANDARD_EVALUATORS = [*PHY_EVALUATORS, *NET_EVALUATORS, *OPS_EVALUATORS, *DATA_EVALUATORS, *MKT_EVALUATORS]

__all__ = ["STANDARD_EVALUATORS", "EVALUATOR_SET_VERSION"]
