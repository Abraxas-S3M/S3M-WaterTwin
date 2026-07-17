"""Licensing / entitlement layer for watertwin-api.

Commercial-hardening work package: **feature-gating by tenant / plan**. This
module decides *which advisory features* a tenant's plan unlocks — it is a
pure product-packaging concern and is deliberately **orthogonal to the safety
boundary**.

Two invariants make that separation explicit and testable:

* **Entitlements never touch the safety invariant.** There is no plan, feature
  flag, or limit anywhere in this module that can set ``control_mode`` to
  anything other than ``advisory``, flip ``operator_approval_required`` off, or
  enable ``control_write_enabled``. Feature-gating can only *hide advisory
  features*; it can never *unlock a control-write path* (there is none to
  unlock). ``safety_invariant_intact()`` asserts this and is covered by tests.

* **Feature-gating is not access control.** Authentication/RBAC (``auth.py``)
  decides *who* may act; entitlements decide *what the deployment's plan
  includes*. A request that is entitlement-gated is refused with **402 Payment
  Required**, never by relaxing any safety property.

Configuration (read from the environment at request time, mirroring ``auth``):

* ``WATERTWIN_PLAN`` — named plan (``enterprise`` default, ``professional``,
  ``standard``, ``starter``). Unset ⇒ ``enterprise`` (all features, unlimited),
  so a default deployment and the existing test-suites keep every feature.
* ``WATERTWIN_TENANT_ID`` — tenant identifier recorded in usage/billing export.
* ``WATERTWIN_LICENSE`` — optional JSON overriding the named plan, e.g.
  ``{"plan": "custom", "features": ["water_quality"], "limits": {"max_assets": 10}}``.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from fastapi import Depends, HTTPException, status

from canonical_water_model import ControlBoundary

from .auth import get_current_user

logger = logging.getLogger("watertwin.licensing")


# --------------------------------------------------------------------------- #
# Feature catalogue
# --------------------------------------------------------------------------- #

# Feature keys are stable, product-facing identifiers for the advisory
# capabilities a plan may include. They gate *reads/what-ifs only* — never a
# control action (the platform has none).
FEATURE_SIMULATION_CENTER = "simulation_center"
FEATURE_WATER_QUALITY = "water_quality"
FEATURE_PREDICTIVE_MAINTENANCE = "predictive_maintenance"
FEATURE_ENERGY_OPTIMIZATION = "energy_optimization"
FEATURE_RESILIENCE = "resilience"
FEATURE_EXECUTIVE_VALUE = "executive_value"
FEATURE_OPERATIONS_ASSISTANT = "operations_assistant"
FEATURE_USAGE_METERING = "usage_metering"
FEATURE_SUPPORT_BUNDLE = "support_bundle"
FEATURE_SIGNED_UPDATES = "signed_updates"

ALL_FEATURES: frozenset[str] = frozenset(
    {
        FEATURE_SIMULATION_CENTER,
        FEATURE_WATER_QUALITY,
        FEATURE_PREDICTIVE_MAINTENANCE,
        FEATURE_ENERGY_OPTIMIZATION,
        FEATURE_RESILIENCE,
        FEATURE_EXECUTIVE_VALUE,
        FEATURE_OPERATIONS_ASSISTANT,
        FEATURE_USAGE_METERING,
        FEATURE_SUPPORT_BUNDLE,
        FEATURE_SIGNED_UPDATES,
    }
)

FEATURE_LABELS: dict[str, str] = {
    FEATURE_SIMULATION_CENTER: "Simulation Center (what-if scenarios)",
    FEATURE_WATER_QUALITY: "Water Quality Intelligence",
    FEATURE_PREDICTIVE_MAINTENANCE: "Equipment & Predictive Maintenance",
    FEATURE_ENERGY_OPTIMIZATION: "Energy Optimization",
    FEATURE_RESILIENCE: "Resilience & Generator Command",
    FEATURE_EXECUTIVE_VALUE: "Executive Value / ROI",
    FEATURE_OPERATIONS_ASSISTANT: "S3M Operations Assistant",
    FEATURE_USAGE_METERING: "Usage metering & billing export",
    FEATURE_SUPPORT_BUNDLE: "In-app support bundles",
    FEATURE_SIGNED_UPDATES: "Signed-update channel",
}

# Usage-limit keys (a limit of ``-1`` means unlimited).
LIMIT_MAX_FACILITIES = "max_facilities"
LIMIT_MAX_ASSETS = "max_assets"
LIMIT_MAX_MONTHLY_INGEST = "max_monthly_ingest_events"

UNLIMITED = -1


def _unlimited_limits() -> dict[str, int]:
    return {
        LIMIT_MAX_FACILITIES: UNLIMITED,
        LIMIT_MAX_ASSETS: UNLIMITED,
        LIMIT_MAX_MONTHLY_INGEST: UNLIMITED,
    }


# --------------------------------------------------------------------------- #
# Named plans
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Plan:
    name: str
    features: frozenset[str]
    limits: dict[str, int] = field(default_factory=_unlimited_limits)


PLANS: dict[str, Plan] = {
    # Default: everything, unlimited. A deployment with no license configured
    # runs as enterprise so nothing is gated by accident.
    "enterprise": Plan(
        name="enterprise",
        features=ALL_FEATURES,
        limits=_unlimited_limits(),
    ),
    "professional": Plan(
        name="professional",
        features=frozenset(ALL_FEATURES - {FEATURE_SIGNED_UPDATES}),
        limits={
            LIMIT_MAX_FACILITIES: 5,
            LIMIT_MAX_ASSETS: 250,
            LIMIT_MAX_MONTHLY_INGEST: 5_000_000,
        },
    ),
    "standard": Plan(
        name="standard",
        features=frozenset(
            {
                FEATURE_SIMULATION_CENTER,
                FEATURE_WATER_QUALITY,
                FEATURE_PREDICTIVE_MAINTENANCE,
                FEATURE_USAGE_METERING,
                FEATURE_SUPPORT_BUNDLE,
            }
        ),
        limits={
            LIMIT_MAX_FACILITIES: 1,
            LIMIT_MAX_ASSETS: 50,
            LIMIT_MAX_MONTHLY_INGEST: 500_000,
        },
    ),
    "starter": Plan(
        name="starter",
        features=frozenset({FEATURE_WATER_QUALITY, FEATURE_SUPPORT_BUNDLE}),
        limits={
            LIMIT_MAX_FACILITIES: 1,
            LIMIT_MAX_ASSETS: 10,
            LIMIT_MAX_MONTHLY_INGEST: 50_000,
        },
    ),
}

DEFAULT_PLAN = "enterprise"


# --------------------------------------------------------------------------- #
# Entitlements
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Entitlements:
    """The resolved entitlement for the current tenant/plan."""

    tenant_id: str
    plan: str
    features: frozenset[str]
    limits: dict[str, int]

    def has_feature(self, feature: str) -> bool:
        return feature in self.features

    def limit(self, key: str) -> int:
        return self.limits.get(key, UNLIMITED)

    def describe(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "plan": self.plan,
            "features": {
                key: {
                    "label": FEATURE_LABELS.get(key, key),
                    "enabled": key in self.features,
                }
                for key in sorted(ALL_FEATURES)
            },
            "enabled_features": sorted(self.features),
            "limits": dict(self.limits),
        }

    def limits_status(self, usage: dict) -> list[dict]:
        """Compare a usage snapshot against this plan's limits (advisory only).

        Exceeding a limit is a *billing* signal — it is surfaced for the
        operator/administrator and never changes any safety property.
        """
        mapping = [
            (LIMIT_MAX_FACILITIES, "facilities"),
            (LIMIT_MAX_ASSETS, "assets"),
            (LIMIT_MAX_MONTHLY_INGEST, "ingest_events"),
        ]
        rows: list[dict] = []
        for limit_key, usage_key in mapping:
            limit = self.limit(limit_key)
            used = int(usage.get(usage_key, 0) or 0)
            rows.append(
                {
                    "metric": usage_key,
                    "used": used,
                    "limit": limit,
                    "unlimited": limit == UNLIMITED,
                    "within_limit": limit == UNLIMITED or used <= limit,
                }
            )
        return rows


def _env(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def tenant_id() -> str:
    return _env("WATERTWIN_TENANT_ID") or "default"


def _plan_name() -> str:
    return (_env("WATERTWIN_PLAN") or DEFAULT_PLAN).lower()


def current_entitlements() -> Entitlements:
    """Resolve the active entitlement from the environment (request-time).

    ``WATERTWIN_LICENSE`` (JSON) takes precedence; otherwise a named plan from
    ``WATERTWIN_PLAN`` is used, defaulting to ``enterprise`` (all features).
    Under **no** circumstances does this affect the control boundary.
    """
    tid = tenant_id()

    raw_license = _env("WATERTWIN_LICENSE")
    if raw_license:
        try:
            doc = json.loads(raw_license)
            plan = str(doc.get("plan") or "custom")
            features = doc.get("features")
            if features is None:
                base = PLANS.get(plan) or PLANS[DEFAULT_PLAN]
                feature_set = base.features
            else:
                feature_set = frozenset(
                    f for f in features if f in ALL_FEATURES
                )
            limits = _unlimited_limits()
            limits.update(
                {k: int(v) for k, v in (doc.get("limits") or {}).items()}
            )
            return Entitlements(
                tenant_id=str(doc.get("tenant_id") or tid),
                plan=plan,
                features=feature_set,
                limits=limits,
            )
        except (ValueError, TypeError) as exc:
            logger.warning(
                "invalid WATERTWIN_LICENSE JSON; falling back to plan",
                extra={"error": str(exc)},
            )

    plan = _plan_name()
    resolved = PLANS.get(plan)
    if resolved is None:
        logger.warning(
            "unknown WATERTWIN_PLAN %r; falling back to %s", plan, DEFAULT_PLAN
        )
        resolved = PLANS[DEFAULT_PLAN]
        plan = DEFAULT_PLAN
    return Entitlements(
        tenant_id=tid,
        plan=resolved.name,
        features=resolved.features,
        limits=dict(resolved.limits),
    )


# --------------------------------------------------------------------------- #
# Safety-invariant guarantee
# --------------------------------------------------------------------------- #


def safety_invariant_intact() -> bool:
    """True iff the advisory/read-only invariant is unaffected by entitlements.

    The control boundary is a fixed default; nothing in this module writes to
    it. This is asserted here (and in tests) so that any future change which
    tried to make a *feature* relax the boundary would be caught immediately.
    """
    cb = ControlBoundary()
    return (
        cb.control_mode == "advisory"
        and cb.operator_approval_required is True
        and cb.control_write_enabled is False
    )


# --------------------------------------------------------------------------- #
# FastAPI dependency
# --------------------------------------------------------------------------- #


def require_feature(feature: str):
    """Return a dependency that admits a request only if the tenant's plan
    includes ``feature``.

    Refuses with **402 Payment Required** when the feature is not entitled.
    This never alters the safety boundary — it only hides an advisory feature
    behind the tenant's plan.
    """

    def _dependency() -> Entitlements:
        ent = current_entitlements()
        if not ent.has_feature(feature):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"feature '{feature}' is not included in the '{ent.plan}' "
                    f"plan for tenant '{ent.tenant_id}'. Upgrade the plan to "
                    "enable it. (This is a licensing limit only and does not "
                    "affect the advisory/read-only safety boundary.)"
                ),
            )
        return ent

    return _dependency


def authed_feature(feature: str) -> list:
    """Convenience: an authenticated + entitlement-gated dependency list for a
    route's ``dependencies=`` argument.

    Order matters only for the error surfaced first: authentication (401/403)
    is checked before entitlement (402).
    """
    return [Depends(get_current_user), Depends(require_feature(feature))]


__all__ = [
    "ALL_FEATURES",
    "FEATURE_LABELS",
    "Entitlements",
    "Plan",
    "PLANS",
    "authed_feature",
    "current_entitlements",
    "require_feature",
    "safety_invariant_intact",
    "tenant_id",
    # feature keys
    "FEATURE_SIMULATION_CENTER",
    "FEATURE_WATER_QUALITY",
    "FEATURE_PREDICTIVE_MAINTENANCE",
    "FEATURE_ENERGY_OPTIMIZATION",
    "FEATURE_RESILIENCE",
    "FEATURE_EXECUTIVE_VALUE",
    "FEATURE_OPERATIONS_ASSISTANT",
    "FEATURE_USAGE_METERING",
    "FEATURE_SUPPORT_BUNDLE",
    "FEATURE_SIGNED_UPDATES",
]
