# D1 Analytics Models

> **Status: PRELIMINARY.** Every threshold, metric and benchmark figure below is
> preliminary and **pending customer calibration**. Nothing here is a validated
> performance guarantee. All D1 models are **advisory and read-only** — they carry
> the read-only control boundary (`control_write_enabled = false`,
> `operator_approval_required = true`) and `provenance = preliminary`, and no model
> writes to any control system.

The **D1 framework** (`packages/watertwin_models`) is the platform's first
analytics-model tier. It provides the metadata, evaluation and monitoring
scaffolding a model needs; it deliberately implements **no** physics. Every
concrete D1 model REUSES the single canonical physics engine
(`watertwin_engineering`) and the existing Water-Quality / Membrane service layer
— nothing is duplicated or re-created — and each ships:

- a full `ModelSpec` (inputs, outputs, baseline, **reused components with
  preserved provenance**, preliminary alert thresholds, drift + calibration +
  false-alarm configuration);
- a synthetic, labelled **back-test dataset** and back-test **metrics** from the
  D1 harness (precision / recall / F1 / accuracy / **false-alarm rate** / lead
  time);
- **preliminary alert thresholds** (all marked `pending_customer_calibration`);
- a **false-alarm tracker** (windowed false-positive accounting against operator
  dispositions);
- a **confidence-calibration** layer (reliability binning + Brier score;
  uncalibrated until customer-labelled data exists); and
- a **drift hook** (population-stability-index feature drift vs the baseline) plus
  a runnable **benchmark stub**.

## Framework components (`watertwin_models`)

| Module | Purpose |
|--------|---------|
| `spec` | `ModelSpec` + `InputSignal`, `BaselineRef`, `ReusedComponent`, `AlertThreshold`, `DriftConfig`, `CalibrationConfig`, `FalseAlarmConfig`. |
| `backtest` | `BackTestDataset`, `LabeledSample`, `run_backtest` → `BackTestMetrics` (confusion matrix, false-alarm rate, lead time). |
| `false_alarm` | `FalseAlarmTracker` → windowed `FalseAlarmSummary` against operator dispositions. |
| `calibration` | `brier_score`, `reliability_curve`, `ConfidenceCalibrator` (identity until fit). |
| `drift` | `population_stability_index`, `FeatureDriftMonitor` → `DriftReport` (stable / watch / drift). |
| `benchmark` | `run_benchmark` → `BenchmarkResult` (back-test + Brier + drift, with a mandatory disclaimer). |

## The three models

### Model 1 — HP-pump condition (`d1-hp-pump-condition`)

- **Inputs:** suction/discharge pressure, flow, speed, power, vibration, bearing
  temperature, seal leakage, pump-curve efficiency deviation, NPSH margin.
- **Outputs:** explainable **pump-health index** + **cavitation probability**.
- **Reuses (not duplicated):** `component_health("pump")` (visible-penalty health),
  `operating_envelope_score` (NPSH margin / cavitation — the documented 0.5 m
  rule), `root_cause_rank` (pump-curve-deviation explainability).

| Threshold (preliminary) | Rule |
|-------------------------|------|
| Vibration high | `vibration_mm_s` ≥ 4.5 (ISO 10816) |
| Bearing temperature high | `bearing_temp_c` ≥ 90 |
| Seal leakage high | `seal_leakage_ml_min` ≥ 5 |
| NPSH margin low (cavitation) | `npsh_margin_m` ≤ 0.5 (reused canonical rule) |
| Cavitation probability high | `cavitation_probability` ≥ 0.5 |
| Pump health degraded | `pump_health_index` ≤ 60 |

### Model 2 — Membrane fouling & salt passage (`d1-membrane-fouling`)

- **Inputs:** normalized permeate flow, normalized salt passage, differential
  pressure, feed conductivity, temperature, recovery, pressure, cleaning history,
  ion chemistry.
- **Outputs:** **membrane-health index** + **salt-passage-breakthrough
  probability** + preliminary CIP recommendation.
- **Reuses (not re-created):** `app.membrane.compute_membrane_health` (which itself
  reuses `app.water_quality`), `app.water_quality.compute_scaling_risks`, and the
  canonical normalized fouling indices.

| Threshold (preliminary) | Rule |
|-------------------------|------|
| Normalized dP rise (CIP) | `normalized_dp_rise_pct` ≥ 15 (reused CIP rule) |
| Normalized salt-passage rise (CIP) | `normalized_salt_passage_rise_pct` ≥ 10 (reused CIP rule) |
| Permeate flow decline | `normalized_permeate_flow_decline_pct` ≥ 10 |
| Salt-passage breakthrough probability high | ≥ 0.5 |
| Membrane health degraded | `membrane_health_index` ≤ 60 |

### Model 3 — Cartridge-filter replacement (`d1-cartridge-filter`)

- **Inputs:** differential pressure, flow, turbidity, particle count, SDI,
  runtime, replacement history.
- **Outputs:** explainable **filter-health index** + **replacement-due
  probability** + preliminary remaining runtime.
- **Reuses (not duplicated):** `component_health("filter")` (normalized-dP health),
  `colloidal_fouling_index` (SDI / turbidity / particle loading),
  `remaining_useful_life_days` (remaining runtime).

| Threshold (preliminary) | Rule |
|-------------------------|------|
| Differential pressure change-out | `normalized_dp` ≥ 2.5× clean |
| SDI high | `sdi` ≥ 5 |
| Replacement-due probability high | ≥ 0.5 |
| Filter health degraded | `filter_health_index` ≤ 60 |

## API (read-only)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/models` | List the registered D1 models. |
| `GET` | `/api/v1/models/{model_id}/spec` | Full `ModelSpec` metadata. |
| `GET` | `/api/v1/models/{model_id}/assessment` | Reference advisory assessment (optional `?fouling=`). |
| `POST` | `/api/v1/models/{model_id}/assessment` | Assessment for arbitrary read-only inputs. |
| `GET` | `/api/v1/models/{model_id}/backtest` | Back-test metrics (optional `?threshold=`). |
| `GET` | `/api/v1/models/{model_id}/benchmark` | Preliminary benchmark (back-test + Brier + drift). |

Every response carries the read-only control boundary and `provenance =
preliminary`.

## Calibration path

The synthetic back-test datasets and benchmark stubs
(`services/watertwin-api/app/models/benchmarks/`) are **scaffolds**. During
customer calibration:

1. replace each synthetic dataset with a customer-labelled dataset;
2. re-run the benchmark stub and record the metrics;
3. fit the `ConfidenceCalibrator` on the labelled outcomes;
4. tune each preliminary threshold against the site's false-alarm tolerance
   (tracked by `FalseAlarmTracker`); and
5. flip the thresholds from `preliminary` / `pending_customer_calibration` to
   validated.

Until then, every threshold and figure remains **preliminary**.
