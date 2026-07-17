"""Deterministic seed for a realistic 15-asset reverse-osmosis (RO) train.

The plant modelled here is a single seawater RO train (``RO-TRAIN-001``) inside
facility ``RO-FACILITY-001``.  Water flows:

    seawater intake -> pretreatment/filtration -> high-pressure pumping ->
    membrane array -> permeate + concentrate (with energy recovery on the
    concentrate side).

All figures are representative nameplate values for a mid-size SWRO train and
contain no real or customer data.
"""

from __future__ import annotations

from watertwin.models import (
    Asset,
    AssetType,
    Criticality,
    RatedData,
    SamplingPoint,
    WaterStream,
)

FACILITY_ID = "RO-FACILITY-001"
TRAIN_ID = "RO-TRAIN-001"


def seed_assets() -> list[Asset]:
    """Return the 15 assets that make up the RO train.

    Asset IDs are stable and must not be renamed -- downstream telemetry,
    scenarios and analytics key off of them.
    """

    return [
        Asset(
            asset_id="INTK-PMP-001",
            name="Seawater Intake Pump",
            asset_type=AssetType.PUMP,
            criticality=Criticality.HIGH,
            rated_data=RatedData(
                rated_flow_m3h=520.0,
                rated_pressure_bar=3.0,
                rated_head_m=30.0,
                rated_power_kw=75.0,
                rated_speed_rpm=1480.0,
                rated_voltage_v=400.0,
                rated_current_a=135.0,
                rated_efficiency_pct=82.0,
            ),
        ),
        Asset(
            asset_id="XFER-PMP-001",
            name="Feed Transfer Pump",
            asset_type=AssetType.PUMP,
            criticality=Criticality.MEDIUM,
            rated_data=RatedData(
                rated_flow_m3h=480.0,
                rated_pressure_bar=4.0,
                rated_head_m=40.0,
                rated_power_kw=55.0,
                rated_speed_rpm=1480.0,
                rated_voltage_v=400.0,
                rated_current_a=100.0,
                rated_efficiency_pct=81.0,
            ),
        ),
        Asset(
            asset_id="CART-FLT-001",
            name="Cartridge Filter Skid",
            asset_type=AssetType.FILTER,
            criticality=Criticality.MEDIUM,
            rated_data=RatedData(
                rated_flow_m3h=470.0,
                rated_pressure_bar=0.4,
                notes="5 micron cartridge filters; clean dP ~0.2 bar, replace at ~1.0 bar dP.",
            ),
        ),
        Asset(
            asset_id="HPP-001",
            name="High-Pressure Feed Pump",
            asset_type=AssetType.PUMP,
            criticality=Criticality.CRITICAL,
            rated_data=RatedData(
                rated_flow_m3h=250.0,
                rated_pressure_bar=68.0,
                rated_head_m=690.0,
                rated_power_kw=630.0,
                rated_speed_rpm=2980.0,
                rated_voltage_v=6600.0,
                rated_current_a=70.0,
                rated_efficiency_pct=84.0,
            ),
        ),
        Asset(
            asset_id="HPP-MOT-001",
            name="High-Pressure Pump Motor",
            asset_type=AssetType.MOTOR,
            criticality=Criticality.CRITICAL,
            parent_id="HPP-001",
            rated_data=RatedData(
                rated_power_kw=670.0,
                rated_speed_rpm=2980.0,
                rated_voltage_v=6600.0,
                rated_current_a=72.0,
                rated_efficiency_pct=96.0,
            ),
        ),
        Asset(
            asset_id="HPP-VFD-001",
            name="High-Pressure Pump VFD",
            asset_type=AssetType.VFD,
            criticality=Criticality.HIGH,
            parent_id="HPP-001",
            rated_data=RatedData(
                rated_power_kw=710.0,
                rated_voltage_v=6600.0,
                rated_current_a=75.0,
                rated_efficiency_pct=98.0,
            ),
        ),
        Asset(
            asset_id="ERD-001",
            name="Isobaric Energy Recovery Device",
            asset_type=AssetType.ENERGY_RECOVERY_DEVICE,
            criticality=Criticality.HIGH,
            rated_data=RatedData(
                rated_flow_m3h=150.0,
                rated_pressure_bar=66.0,
                rated_efficiency_pct=96.0,
                notes="Pressure exchanger transferring energy from concentrate to feed.",
            ),
        ),
        Asset(
            asset_id="RO-ARR-001",
            name="RO Membrane Array",
            asset_type=AssetType.MEMBRANE_ARRAY,
            criticality=Criticality.CRITICAL,
            rated_data=RatedData(
                rated_flow_m3h=250.0,
                rated_pressure_bar=65.0,
                notes="Spiral-wound SWRO elements; permeate ~110 m3/h at 45% recovery.",
            ),
        ),
        Asset(
            asset_id="BST-PMP-001",
            name="Booster Pump",
            asset_type=AssetType.PUMP,
            criticality=Criticality.MEDIUM,
            rated_data=RatedData(
                rated_flow_m3h=150.0,
                rated_pressure_bar=3.0,
                rated_head_m=30.0,
                rated_power_kw=30.0,
                rated_speed_rpm=2960.0,
                rated_voltage_v=400.0,
                rated_current_a=55.0,
                rated_efficiency_pct=80.0,
            ),
        ),
        Asset(
            asset_id="DOSE-PMP-001",
            name="Antiscalant Dosing Pump",
            asset_type=AssetType.PUMP,
            criticality=Criticality.LOW,
            rated_data=RatedData(
                rated_flow_m3h=0.5,
                rated_pressure_bar=6.0,
                rated_power_kw=1.5,
                rated_speed_rpm=1400.0,
                rated_voltage_v=400.0,
                rated_current_a=3.5,
                rated_efficiency_pct=60.0,
            ),
        ),
        Asset(
            asset_id="CV-001",
            name="Concentrate Control Valve",
            asset_type=AssetType.CONTROL_VALVE,
            criticality=Criticality.HIGH,
            rated_data=RatedData(
                rated_flow_m3h=140.0,
                rated_pressure_bar=70.0,
                notes="Modulates concentrate flow to hold membrane recovery.",
            ),
        ),
        Asset(
            asset_id="PERM-PMP-001",
            name="Permeate Transfer Pump",
            asset_type=AssetType.PUMP,
            criticality=Criticality.MEDIUM,
            rated_data=RatedData(
                rated_flow_m3h=115.0,
                rated_pressure_bar=4.0,
                rated_head_m=40.0,
                rated_power_kw=22.0,
                rated_speed_rpm=2950.0,
                rated_voltage_v=400.0,
                rated_current_a=42.0,
                rated_efficiency_pct=78.0,
            ),
        ),
        Asset(
            asset_id="BRN-PMP-001",
            name="Brine Discharge Pump",
            asset_type=AssetType.PUMP,
            criticality=Criticality.MEDIUM,
            rated_data=RatedData(
                rated_flow_m3h=140.0,
                rated_pressure_bar=2.5,
                rated_head_m=25.0,
                rated_power_kw=18.5,
                rated_speed_rpm=1470.0,
                rated_voltage_v=400.0,
                rated_current_a=35.0,
                rated_efficiency_pct=79.0,
            ),
        ),
        Asset(
            asset_id="XFMR-001",
            name="Main Power Transformer",
            asset_type=AssetType.TRANSFORMER,
            criticality=Criticality.HIGH,
            rated_data=RatedData(
                rated_capacity_kva=2000.0,
                rated_voltage_v=11000.0,
                rated_temperature_c=65.0,
                notes="11 kV / 690 V oil-filled distribution transformer.",
            ),
        ),
        Asset(
            asset_id="GEN-001",
            name="Standby Diesel Generator",
            asset_type=AssetType.GENERATOR,
            criticality=Criticality.HIGH,
            rated_data=RatedData(
                rated_power_kw=1500.0,
                rated_voltage_v=400.0,
                notes="Standby genset for grid-outage ride-through.",
            ),
        ),
    ]


def seed_streams() -> list[WaterStream]:
    """Return the 5 process water streams for the RO train."""

    return [
        WaterStream(
            stream_id="SW-FEED-001",
            name="seawater_feed",
            description="Raw seawater drawn from the intake structure.",
            nominal_flow_m3h=520.0,
            nominal_tds_mg_l=38000.0,
            nominal_pressure_bar=3.0,
        ),
        WaterStream(
            stream_id="PT-FEED-001",
            name="pretreated_feed",
            description="Coagulated, dosed and clarified feed ahead of cartridge filtration.",
            nominal_flow_m3h=480.0,
            nominal_tds_mg_l=37800.0,
            nominal_pressure_bar=2.5,
        ),
        WaterStream(
            stream_id="RO-FEED-001",
            name="ro_feed",
            description="High-pressure feed delivered to the membrane array.",
            nominal_flow_m3h=250.0,
            nominal_tds_mg_l=37800.0,
            nominal_pressure_bar=65.0,
        ),
        WaterStream(
            stream_id="PERM-001",
            name="permeate",
            description="Desalinated permeate produced by the membranes.",
            nominal_flow_m3h=112.0,
            nominal_tds_mg_l=250.0,
            nominal_pressure_bar=1.0,
        ),
        WaterStream(
            stream_id="CONC-001",
            name="concentrate",
            description="High-salinity concentrate / brine routed to energy "
            "recovery and product-water balance.",
            nominal_flow_m3h=138.0,
            nominal_tds_mg_l=68000.0,
            nominal_pressure_bar=63.0,
        ),
    ]


def seed_sampling_points() -> list[SamplingPoint]:
    """Return the 7 sampling points distributed across the treatment stages."""

    return [
        SamplingPoint(
            point_id="SP-01",
            name="Seawater Intake Sample",
            stream_id="SW-FEED-001",
            stage="intake",
            parameters=("turbidity", "temperature", "conductivity", "ph"),
        ),
        SamplingPoint(
            point_id="SP-03",
            name="Pretreated Feed Sample",
            stream_id="PT-FEED-001",
            stage="pretreatment",
            parameters=("turbidity", "sdi", "ph", "orp"),
        ),
        SamplingPoint(
            point_id="SP-05",
            name="Cartridge Filter Outlet Sample",
            stream_id="PT-FEED-001",
            stage="filtration",
            parameters=("sdi", "turbidity", "pressure"),
        ),
        SamplingPoint(
            point_id="SP-08",
            name="RO Feed Sample",
            stream_id="RO-FEED-001",
            stage="high_pressure_feed",
            parameters=("pressure", "conductivity", "temperature"),
        ),
        SamplingPoint(
            point_id="SP-12",
            name="Permeate Sample",
            stream_id="PERM-001",
            stage="membrane",
            parameters=("conductivity", "flow", "ph"),
        ),
        SamplingPoint(
            point_id="SP-16",
            name="Concentrate Sample",
            stream_id="CONC-001",
            stage="membrane",
            parameters=("pressure", "conductivity", "flow"),
        ),
        SamplingPoint(
            point_id="SP-20",
            name="Product Water Sample",
            stream_id="PERM-001",
            stage="product",
            parameters=("conductivity", "ph", "chlorine"),
        ),
    ]
