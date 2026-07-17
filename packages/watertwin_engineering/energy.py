"""Constrained RO energy-optimization physics (advisory, preliminary).

This module answers a single question: for the deterministic reverse-osmosis
model already defined in this package, what high-pressure-pump discharge pressure
and system recovery *minimise specific energy consumption* (SEC) while respecting
the plant's operating constraints?

It **reuses** the canonical RO physics -- :func:`osmotic_pressure_bar`,
:func:`net_driving_pressure_bar`, :func:`water_flux_lmh`, :func:`boron_rejection`
and, for SEC, the single canonical :func:`specific_energy` -- and never
reimplements them. A candidate operating point is a ``(feed_pressure, recovery)``
pair; the forward evaluation composes those primitives exactly as
:func:`ro_performance` does (mean-element concentration factor + solution-
diffusion salt transport). The optimiser is :func:`scipy.optimize.minimize`
(bounded SLSQP) seeded from a feasible coarse grid, so the returned point is
guaranteed feasible and never violates a constraint.

Everything here is advisory and preliminary. SEC is deterministic engineering
math, but every *saving* / *cost* figure is an ESTIMATED number on a synthetic
basis -- not a validated or guaranteed saving. The physics package stays
transport/schema-free; the API layer maps these dataclasses onto the canonical
``EnergyOptimizationResult`` / ``EnergyLoss`` models (provenance = estimated).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from watertwin_engineering.calculations import specific_energy
from watertwin_engineering.osmotic import osmotic_pressure_bar
from watertwin_engineering.ro import net_driving_pressure_bar
from watertwin_engineering.water_quality import boron_rejection

#: Provenance tag for the estimated saving/cost figures produced here.
ESTIMATED = "estimated"

#: Concentration-polarisation factor used when composing the mean-element
#: osmotic pressure (documented screening value; the same order used by the
#: lumped reference model).
_BETA = 1.05


@dataclass(frozen=True)
class OperatingPoint:
    """A single evaluated RO operating point (deterministic physics)."""

    feed_pressure_bar: float
    recovery: float
    sec_kwh_m3: float
    feed_flow_m3h: float
    permeate_flow_m3h: float
    permeate_tds_mg_l: float
    permeate_boron_mg_l: float
    water_flux_lmh: float
    net_driving_pressure_bar: float
    npsh_margin_m: float
    feasible: bool
    binding_constraints: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ROEnergyOptimization:
    """Baseline-vs-optimised RO energy result with ESTIMATED savings.

    ``baseline`` is the plant's current operating point; ``optimal`` is the
    minimum-SEC feasible point found by the bounded optimiser. All saving/cost
    figures are estimated on a synthetic basis -- not validated savings.
    """

    baseline: OperatingPoint
    optimal: OperatingPoint
    sec_reduction_kwh_m3: float
    sec_reduction_pct: float
    estimated_energy_saving_kwh_day: float
    estimated_cost_saving_per_day: float
    tariff_per_kwh: float
    operating_hours_per_day: float
    method: str
    provenance: str = ESTIMATED


# ---------------------------------------------------------------------------
# Simple, documented cost helpers.
# ---------------------------------------------------------------------------


def energy_cost(
    kwh: float,
    tariff: float,
    peak_flag: bool = False,
    peak_multiplier: float = 1.5,
    demand_kw: float | None = None,
    demand_charge_per_kw: float = 0.0,
) -> float:
    """Estimated cost of ``kwh`` energy at ``tariff`` (currency/kWh).

    A peak-tariff multiplier is applied when ``peak_flag`` is set, and an
    optional peak-demand term (``demand_kw * demand_charge_per_kw``) can be
    added. This is a screening estimate, not a billed tariff.

    Args:
        kwh: Energy in kWh (>= 0).
        tariff: Energy price per kWh (>= 0).
        peak_flag: Whether the peak-tariff multiplier applies.
        peak_multiplier: Multiplier applied to the energy term at peak (>= 1).
        demand_kw: Optional peak demand in kW for a demand charge.
        demand_charge_per_kw: Demand charge per kW (>= 0).

    Returns:
        Estimated cost in the tariff's currency (>= 0).

    Raises:
        ValueError: If any argument is negative or ``peak_multiplier < 1``.
    """
    if kwh < 0:
        raise ValueError("kwh must be non-negative.")
    if tariff < 0:
        raise ValueError("tariff must be non-negative.")
    if peak_multiplier < 1.0:
        raise ValueError("peak_multiplier must be >= 1.")
    if demand_charge_per_kw < 0:
        raise ValueError("demand_charge_per_kw must be non-negative.")
    energy_term = kwh * tariff * (peak_multiplier if peak_flag else 1.0)
    demand_term = 0.0
    if demand_kw is not None:
        if demand_kw < 0:
            raise ValueError("demand_kw must be non-negative.")
        demand_term = demand_kw * demand_charge_per_kw
    return energy_term + demand_term


def avoidable_energy_loss(current_sec: float, best_achievable_sec: float) -> float:
    """Avoidable specific-energy loss in kWh/m^3 (>= 0).

    The avoidable loss is the amount by which the current SEC exceeds the best
    achievable SEC. Clamped at zero (the current point cannot beat the optimum).

    Raises:
        ValueError: If either SEC is negative.
    """
    if current_sec < 0 or best_achievable_sec < 0:
        raise ValueError("specific energy values must be non-negative.")
    return max(0.0, current_sec - best_achievable_sec)


# ---------------------------------------------------------------------------
# Forward RO model (composes the canonical primitives; no new physics).
# ---------------------------------------------------------------------------


def _get(d: dict, key: str, default: float) -> float:
    value = d.get(key, default)
    return float(value if value is not None else default)


def _mean_concentration_factor(recovery: float) -> float:
    """Mean-element concentration factor (average of feed 1x and concentrate)."""
    return 0.5 * (1.0 + 1.0 / max(1e-6, 1.0 - recovery))


def evaluate_operating_point(
    feed: dict,
    membrane_state: dict,
    feed_pressure_bar: float,
    recovery: float,
    constraints: dict | None = None,
) -> OperatingPoint:
    """Evaluate one ``(feed_pressure, recovery)`` operating point.

    Reuses the canonical RO primitives: osmotic pressure, net driving pressure,
    the solution-diffusion flux relation, boron rejection and the single
    canonical :func:`specific_energy`. The train runs at a nameplate feed flow
    (``feed_flow_m3h``); recovery is set by the concentrate valve, so permeate
    flow is ``feed_flow * recovery`` and pressure sets the *available* driving
    pressure. A point is feasible only when the applied pressure delivers at
    least the driving pressure the target flux requires (``insufficient_pressure``
    otherwise) and every other constraint holds.
    """
    constraints = constraints or {}
    feed_tds = _get(feed, "tds_mg_l", 45000.0)
    temperature_c = _get(feed, "temperature_c", 25.0)
    feed_boron = _get(feed, "boron_mg_l", 5.0)
    feed_ph = _get(feed, "ph", 7.8)

    feed_flow_m3h = _get(membrane_state, "feed_flow_m3h", 500.0)
    area_m2 = _get(membrane_state, "membrane_area_m2", 16000.0)
    a_lmh_bar = _get(membrane_state, "permeability_a_lmh_bar", 3.0)
    b_lmh = _get(membrane_state, "salt_permeability_b_lmh", 0.15)
    age_factor = _get(membrane_state, "membrane_age_factor", 1.0)
    pump_eff = _get(membrane_state, "pump_efficiency", 0.8)
    erd_eff = _get(membrane_state, "erd_efficiency", 0.95)
    use_erd = bool(membrane_state.get("use_erd", True))
    pressure_drop_bar = _get(membrane_state, "pressure_drop_bar", 1.0)
    npsh_available_m = _get(membrane_state, "npsh_available_m", 6.0)
    npsh_required_m = _get(membrane_state, "npsh_required_m", 3.0)

    recovery = min(max(recovery, 1e-3), 0.95)
    beta = _BETA

    # Recovery is set by the concentrate valve at the nameplate feed flow.
    permeate_flow_m3h = feed_flow_m3h * recovery
    flux_lmh = permeate_flow_m3h * 1000.0 / area_m2 if area_m2 > 0 else 0.0

    # Osmotic pressure at the mean element (recovery raises the concentrate side).
    pi_feed = osmotic_pressure_bar(feed_tds, temperature_c)
    cf_mean = _mean_concentration_factor(recovery)
    pi_mean = pi_feed * cf_mean * beta

    # Applied (available) NDP from the pump vs the NDP the target flux requires.
    ndp_available = net_driving_pressure_bar(
        feed_pressure_bar=feed_pressure_bar,
        permeate_pressure_bar=0.0,
        feed_side_osmotic_bar=pi_mean,
        permeate_osmotic_bar=0.0,
        feed_channel_dp_bar=pressure_drop_bar,
    )
    ndp_required = flux_lmh / a_lmh_bar if a_lmh_bar > 0 else float("inf")

    # Specific energy via the single canonical implementation.
    sec = specific_energy(
        feed_flow_m3h=feed_flow_m3h,
        feed_pressure_bar=feed_pressure_bar,
        recovery=recovery,
        pump_efficiency=pump_eff,
        erd_efficiency=erd_eff,
        use_erd=use_erd,
        pressure_drop_bar=pressure_drop_bar,
    )

    # Salt transport (solution-diffusion): permeate TDS from the mean wall value.
    c_wall_g_l = (feed_tds / 1000.0) * cf_mean * beta
    js = b_lmh * c_wall_g_l  # g/m2/h
    if permeate_flow_m3h > 1e-9:
        permeate_tds = min(js * area_m2 / permeate_flow_m3h, feed_tds)
    else:
        permeate_tds = feed_tds

    # Permeate boron reuses the canonical speciation + membrane-age model.
    b_rej = boron_rejection(
        ph=feed_ph, temperature_c=temperature_c, membrane_age_factor=age_factor
    )
    permeate_boron = feed_boron * (1.0 - b_rej)

    # NPSH margin (cavitation screening): available suction head vs required.
    npsh_margin = npsh_available_m - npsh_required_m

    binding = _binding_constraints(
        constraints,
        feed_pressure_bar=feed_pressure_bar,
        recovery=recovery,
        permeate_flow_m3h=permeate_flow_m3h,
        permeate_tds=permeate_tds,
        permeate_boron=permeate_boron,
        flux_lmh=flux_lmh,
        npsh_margin=npsh_margin,
        ndp_available=ndp_available,
        ndp_required=ndp_required,
    )
    return OperatingPoint(
        feed_pressure_bar=round(feed_pressure_bar, 4),
        recovery=round(recovery, 5),
        sec_kwh_m3=round(sec, 5),
        feed_flow_m3h=round(feed_flow_m3h, 3),
        permeate_flow_m3h=round(permeate_flow_m3h, 3),
        permeate_tds_mg_l=round(permeate_tds, 3),
        permeate_boron_mg_l=round(permeate_boron, 4),
        water_flux_lmh=round(flux_lmh, 4),
        net_driving_pressure_bar=round(ndp_available, 4),
        npsh_margin_m=round(npsh_margin, 4),
        feasible=len(binding) == 0,
        binding_constraints=binding,
    )


def _binding_constraints(
    constraints: dict,
    *,
    feed_pressure_bar: float,
    recovery: float,
    permeate_flow_m3h: float,
    permeate_tds: float,
    permeate_boron: float,
    flux_lmh: float,
    npsh_margin: float,
    ndp_available: float,
    ndp_required: float,
) -> list[str]:
    """Return the names of any violated constraints (empty when feasible)."""
    violated: list[str] = []
    tol = 1e-6
    c = constraints

    def upper(key: str, value: float, label: str) -> None:
        limit = c.get(key)
        if limit is not None and value > float(limit) + tol:
            violated.append(label)

    def lower(key: str, value: float, label: str) -> None:
        limit = c.get(key)
        if limit is not None and value < float(limit) - tol:
            violated.append(label)

    # The applied pressure must supply at least the driving pressure the target
    # flux requires (always enforced -- a physical feasibility requirement).
    if ndp_available < ndp_required - tol:
        violated.append("insufficient_pressure")
    lower("min_permeate_flow_m3h", permeate_flow_m3h, "min_permeate_flow")
    upper("max_permeate_flow_m3h", permeate_flow_m3h, "max_permeate_flow")
    upper("max_permeate_tds_mg_l", permeate_tds, "max_permeate_tds")
    upper("max_permeate_boron_mg_l", permeate_boron, "max_permeate_boron")
    upper("max_pressure_bar", feed_pressure_bar, "max_pressure")
    lower("min_pressure_bar", feed_pressure_bar, "min_pressure")
    upper("max_flux_lmh", flux_lmh, "max_flux")
    lower("min_recovery", recovery, "min_recovery")
    upper("max_recovery", recovery, "max_recovery")
    lower("min_npsh_margin_m", npsh_margin, "cavitation_npsh_margin")
    return violated


# ---------------------------------------------------------------------------
# Bounded optimisation.
# ---------------------------------------------------------------------------


def _pressure_bounds(constraints: dict) -> tuple[float, float]:
    p_min = float(constraints.get("min_pressure_bar", 30.0))
    p_max = float(constraints.get("max_pressure_bar", 80.0))
    if p_max <= p_min:
        raise ValueError("max_pressure_bar must exceed min_pressure_bar.")
    return p_min, p_max


def _recovery_bounds(constraints: dict) -> tuple[float, float]:
    r_min = float(constraints.get("min_recovery", 0.30))
    r_max = float(constraints.get("max_recovery", 0.55))
    if r_max <= r_min:
        raise ValueError("max_recovery must exceed min_recovery.")
    return r_min, r_max


def ro_operating_point_optimization(
    feed: dict,
    membrane_state: dict,
    constraints: dict,
) -> ROEnergyOptimization:
    """Find the min-SEC feasible RO operating point (bounded optimisation).

    Minimises specific energy consumption over the high-pressure-pump discharge
    pressure and system recovery using :func:`scipy.optimize.minimize` (bounded
    SLSQP), subject to: min/max permeate flow, product-water quality limits
    (permeate TDS + boron), max/min pressure, cavitation/NPSH margin, membrane
    flux limit and the recovery range. A feasible coarse grid seeds the solver so
    the returned point is guaranteed feasible; the solver result is only accepted
    when it is feasible and lowers SEC.

    Args:
        feed: Feed composition (``tds_mg_l``, ``temperature_c``, ``boron_mg_l``,
            ``ph``) plus the baseline operating point (``feed_pressure_bar``,
            ``recovery``).
        membrane_state: Membrane/pump parameters (area, A/B coefficients, age
            factor, efficiencies, pressure drop, NPSH available/required).
        constraints: Operating constraints + economic inputs (``tariff_per_kwh``,
            ``peak_flag``, ``operating_hours_per_day``).

    Returns:
        A :class:`ROEnergyOptimization` with baseline vs optimal points and the
        ESTIMATED energy + cost deltas.

    Raises:
        ValueError: If no feasible operating point exists in the given bounds.
    """
    p_min, p_max = _pressure_bounds(constraints)
    r_min, r_max = _recovery_bounds(constraints)

    def sec_of(p: float, r: float) -> float:
        op = evaluate_operating_point(feed, membrane_state, p, r, constraints)
        return op.sec_kwh_m3 if isinstance(op.sec_kwh_m3, float) else float("inf")

    # 1) Feasible coarse grid -> a guaranteed-feasible seed + global screen.
    seed: tuple[float, float] | None = None
    seed_sec = float("inf")
    steps_p = 25
    steps_r = 25
    for i in range(steps_p + 1):
        p = p_min + (p_max - p_min) * i / steps_p
        for j in range(steps_r + 1):
            r = r_min + (r_max - r_min) * j / steps_r
            op = evaluate_operating_point(feed, membrane_state, p, r, constraints)
            if op.feasible and isinstance(op.sec_kwh_m3, float) and op.sec_kwh_m3 < seed_sec:
                seed_sec = op.sec_kwh_m3
                seed = (p, r)

    if seed is None:
        raise ValueError(
            "No feasible RO operating point exists within the given constraints."
        )

    # 2) Refine with a bounded SLSQP minimize seeded from the feasible grid best.
    # scipy is imported lazily so importing this package never requires scipy for
    # consumers that don't run the optimiser (e.g. the treatment-sim reference).
    from scipy.optimize import minimize

    big = 1e6

    def objective(x: list[float]) -> float:
        sec = sec_of(x[0], x[1])
        return sec if sec != float("inf") else big

    def feasibility(x: list[float]) -> float:
        # >= 0 when feasible: negative margin => infeasible.
        op = evaluate_operating_point(feed, membrane_state, x[0], x[1], constraints)
        return 0.0 if op.feasible else -1.0

    best_p, best_r = seed
    best_sec = seed_sec
    try:
        result = minimize(
            objective,
            x0=[seed[0], seed[1]],
            method="SLSQP",
            bounds=[(p_min, p_max), (r_min, r_max)],
            constraints=[{"type": "ineq", "fun": feasibility}],
            options={"maxiter": 200, "ftol": 1e-6},
        )
        cand_p, cand_r = float(result.x[0]), float(result.x[1])
        cand_op = evaluate_operating_point(feed, membrane_state, cand_p, cand_r, constraints)
        if (
            cand_op.feasible
            and isinstance(cand_op.sec_kwh_m3, float)
            and cand_op.sec_kwh_m3 <= best_sec + 1e-9
        ):
            best_p, best_r, best_sec = cand_p, cand_r, cand_op.sec_kwh_m3
    except Exception:  # pragma: no cover - solver robustness; grid seed remains
        pass

    optimal = evaluate_operating_point(feed, membrane_state, best_p, best_r, constraints)

    # Baseline = the plant's current operating point (must be within bounds).
    baseline_p = _get(feed, "feed_pressure_bar", p_max)
    baseline_r = _get(feed, "recovery", r_min)
    baseline = evaluate_operating_point(feed, membrane_state, baseline_p, baseline_r, constraints)

    baseline_sec = baseline.sec_kwh_m3
    reduction = avoidable_energy_loss(baseline_sec, optimal.sec_kwh_m3)
    if baseline_sec not in (0.0, float("inf")):
        reduction_pct = reduction / baseline_sec * 100.0
    else:
        reduction_pct = 0.0

    tariff = float(constraints.get("tariff_per_kwh", 0.08))
    hours = float(constraints.get("operating_hours_per_day", 24.0))
    peak_flag = bool(constraints.get("peak_flag", False))

    # ESTIMATED daily saving on optimal permeate production (synthetic basis).
    permeate_m3_day = optimal.permeate_flow_m3h * hours
    energy_saving_kwh_day = reduction * permeate_m3_day
    cost_saving_day = energy_cost(energy_saving_kwh_day, tariff, peak_flag=peak_flag)

    return ROEnergyOptimization(
        baseline=baseline,
        optimal=optimal,
        sec_reduction_kwh_m3=round(reduction, 5),
        sec_reduction_pct=round(reduction_pct, 3),
        estimated_energy_saving_kwh_day=round(energy_saving_kwh_day, 2),
        estimated_cost_saving_per_day=round(cost_saving_day, 2),
        tariff_per_kwh=tariff,
        operating_hours_per_day=hours,
        method="scipy.optimize.minimize (bounded SLSQP) over the deterministic RO model",
        provenance=ESTIMATED,
    )
