"""RO-TRAIN-001 product-water handoff network for hydraulic what-if simulation.

The network represents the finished / product-water side of RO-TRAIN-001: the
remineralized permeate buffer (``R-PERM``), two parallel product-water transfer
pumps (``PU-PROD-1`` / ``PU-PROD-2``), an elevated product-water storage tank
(``T-PROD``), a metered handoff valve (``CV-HANDOFF``) and the distribution
handoff demand nodes (``J-D1`` .. ``J-D3``).

The canonical model artifact is ``models/ro-handoff.inp`` (a standard EPANET input
file). :func:`build_ro_handoff_network` reproduces that same network in code and
is used to (re)generate the ``.inp`` and as an in-memory fallback.

Units note: WNTR's in-memory API is SI (flow in m^3/s), so demands/curve points
are converted from m^3/h with :data:`CMH`.
"""

from __future__ import annotations

import os

import wntr

CMH = 1.0 / 3600.0  # cubic metres per hour -> cubic metres per second

DEFAULT_INP = os.path.join(os.path.dirname(__file__), "..", "models", "ro-handoff.inp")

# Element ids surfaced to clients / scenarios.
PUMPS = ["PU-PROD-1", "PU-PROD-2"]
VALVES = ["CV-HANDOFF"]
TANKS = ["T-PROD"]
DEMAND_NODES = ["J-D1", "J-D2", "J-D3"]
SUPPLY_NODES = ["R-PERM"]

REQUIRED_PRESSURE_M = 25.0
MINIMUM_PRESSURE_M = 0.0
MAX_VELOCITY_M_S = 3.0

# The tank buffer connector is intentionally throttled (small bore) to model the
# storage tie-in resistance; its velocity is not a service constraint.
EXCLUDE_VELOCITY_LINKS = {"P-TANK"}


def build_ro_handoff_network() -> "wntr.network.WaterNetworkModel":
    """Build the RO-TRAIN-001 product-water handoff network in code."""
    wn = wntr.network.WaterNetworkModel()
    wn.options.hydraulic.inpfile_units = "CMH"
    wn.options.hydraulic.headloss = "H-W"
    wn.options.hydraulic.demand_model = "PDA"
    wn.options.hydraulic.required_pressure = REQUIRED_PRESSURE_M
    wn.options.hydraulic.minimum_pressure = MINIMUM_PRESSURE_M
    wn.options.time.duration = 0

    # --- Nodes ---
    wn.add_reservoir("R-PERM", base_head=30.0, coordinates=(0, 0))
    wn.add_junction("J-PS", base_demand=0.0, elevation=0.0, coordinates=(1, 0))
    wn.add_junction("J-PD", base_demand=0.0, elevation=0.0, coordinates=(2, 0))
    wn.add_junction("J-HANDOFF", base_demand=0.0, elevation=18.0, coordinates=(3, 0))
    wn.add_tank(
        "T-PROD",
        elevation=34.0,
        init_level=4.0,
        min_level=0.0,
        max_level=8.0,
        diameter=12.0,
        coordinates=(3, 2),
    )
    wn.add_junction("J-D1", base_demand=200.0 * CMH, elevation=18.0, coordinates=(4, 0))
    wn.add_junction("J-D2", base_demand=190.0 * CMH, elevation=18.0, coordinates=(5, 1))
    wn.add_junction("J-D3", base_demand=170.0 * CMH, elevation=18.0, coordinates=(5, -1))

    # --- Pumps (two parallel product-water transfer pumps) ---
    wn.add_curve("C-PROD", "HEAD", [(0.0, 58.0), (150.0 * CMH, 48.0), (300.0 * CMH, 28.0)])
    wn.add_pump("PU-PROD-1", "J-PS", "J-PD", pump_type="HEAD", pump_parameter="C-PROD")
    wn.add_pump("PU-PROD-2", "J-PS", "J-PD", pump_type="HEAD", pump_parameter="C-PROD")

    # --- Metered handoff valve ---
    wn.add_valve(
        "CV-HANDOFF", "J-PD", "J-HANDOFF", diameter=0.5, valve_type="TCV", initial_setting=0.0
    )

    # --- Pipes ---
    wn.add_pipe("P-SUCT", "R-PERM", "J-PS", length=20, diameter=0.5, roughness=140)
    wn.add_pipe("P-TANK", "J-HANDOFF", "T-PROD", length=80, diameter=0.1, roughness=140)
    wn.add_pipe("P-MAIN", "J-HANDOFF", "J-D1", length=800, diameter=0.4, roughness=140)
    wn.add_pipe("P-D12", "J-D1", "J-D2", length=600, diameter=0.3, roughness=140)
    wn.add_pipe("P-D13", "J-D1", "J-D3", length=600, diameter=0.3, roughness=140)
    return wn


def load_network(inp_path: str | None = None) -> "wntr.network.WaterNetworkModel":
    """Load the network from ``ro-handoff.inp`` when present, else build in code.

    Pressure-dependent-demand options are (re)asserted after load so the engine
    behaviour is identical regardless of source.
    """
    path = inp_path or DEFAULT_INP
    if os.path.exists(path):
        wn = wntr.network.WaterNetworkModel(path)
    else:
        wn = build_ro_handoff_network()
    wn.options.hydraulic.demand_model = "PDA"
    wn.options.hydraulic.required_pressure = REQUIRED_PRESSURE_M
    wn.options.hydraulic.minimum_pressure = MINIMUM_PRESSURE_M
    wn.options.time.duration = 0
    return wn


if __name__ == "__main__":  # pragma: no cover - regenerate the .inp artifact
    target = os.path.abspath(DEFAULT_INP)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    wntr.network.write_inpfile(build_ro_handoff_network(), target)
    print(f"wrote {target}")
