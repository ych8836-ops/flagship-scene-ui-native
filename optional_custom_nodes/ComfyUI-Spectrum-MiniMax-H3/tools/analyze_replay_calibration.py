#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import pathlib
from dataclasses import dataclass
from typing import Any, Iterable

SCHEMA_VERSION = 1
LOG_PREFIX = "SPECTRUM_REPLAY_CALIBRATION_JSON="
DEFAULT_PARITY_TOLERANCE = 2e-5
FIXED_ABSOLUTE_WEIGHTS = (0.0, 0.25, 0.50, 0.75, 1.0)
FIXED_ALPHAS = (0.0, 0.25, 0.50, 0.75, 1.0)
LEVEL2_PREDICTORS = (
    "causal_disagreement",
    "validation_penalty",
    "spectral_gap",
    "coordinate",
)
FIT_RIDGE = 1e-8


class CalibrationError(ValueError):
    pass


@dataclass(frozen=True)
class RunBlock:
    source: str
    block_index: int
    label: str
    seed: int | None
    block: dict[str, Any]

    @property
    def rows(self) -> list[dict[str, Any]]:
        return self.block["target_rows"]

    @property
    def trace_fingerprint(self) -> str:
        value = (self.block.get("provenance") or {}).get("trace_fingerprint")
        if not isinstance(value, str) or not value:
            raise CalibrationError(f"run {self.label!r} has no trace_fingerprint")
        return value

    @property
    def runtime_seed(self) -> int | None:
        value = (self.block.get("provenance") or {}).get("seed")
        if value is None:
            return None
        if isinstance(value, bool):
            raise CalibrationError(f"run {self.label!r} has invalid runtime seed")
        try:
            converted = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise CalibrationError(f"run {self.label!r} has invalid runtime seed") from exc
        if converted != value:
            raise CalibrationError(f"run {self.label!r} has non-integral runtime seed")
        return converted

    @property
    def analysis_identity(self) -> str:
        seed_text = "unknown" if self.seed is None else str(self.seed)
        return f"{self.trace_fingerprint}:seed={seed_text}"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    level: int
    predictor: str | None = None


def clamp_weight(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def ratio_from_row(row: dict[str, Any], weight: float) -> float:
    w = clamp_weight(weight)
    a = float(row["local_error_sq_mean"])
    b = float(row["local_error_dot_spectral_delta_mean"])
    c = float(row["spectral_delta_sq_mean"])
    denominator = float(row["ratio_denominator_rms"])
    if not all(math.isfinite(value) for value in (a, b, c, denominator)):
        raise CalibrationError("nonfinite quadratic calibration value")
    if denominator <= 0.0:
        raise CalibrationError("ratio_denominator_rms must be positive")
    mse = a + 2.0 * w * b + w * w * c
    tolerance = 1e-12 * max(1.0, abs(a), abs(b), abs(c))
    if mse < 0.0 and abs(mse) <= tolerance:
        mse = 0.0
    if mse < 0.0 or not math.isfinite(mse):
        raise CalibrationError("quadratic calibration produced invalid MSE")
    return math.sqrt(mse) / denominator


def oracle_weight_from_row(row: dict[str, Any]) -> float:
    b = float(row["local_error_dot_spectral_delta_mean"])
    c = float(row["spectral_delta_sq_mean"])
    epsilon = float(row["ratio_epsilon"])
    denominator = max(c, epsilon * epsilon)
    if denominator <= 0.0 or not math.isfinite(denominator):
        return 0.0
    return clamp_weight(-b / denominator)


def _fixed_suffix(value: float) -> str:
    return f"{value:.2f}".replace(".", "p")


def validate_row_parity(
    row: dict[str, Any],
    *,
    tolerance: float,
) -> float:
    checks: list[tuple[str, float, float]] = [
        ("local", ratio_from_row(row, 0.0), float(row["local_ratio"])),
        (
            "full_spectral",
            ratio_from_row(row, 1.0),
            float(row["full_spectral_ratio"]),
        ),
        (
            "current",
            ratio_from_row(row, float(row["current_weight"])),
            float(row["current_ratio"]),
        ),
    ]
    oracle_weight = oracle_weight_from_row(row)
    checks.extend(
        (
            ("oracle_weight", oracle_weight, float(row["oracle_weight"])),
            (
                "oracle_ratio",
                ratio_from_row(row, oracle_weight),
                float(row["oracle_ratio"]),
            ),
        )
    )
    for value in FIXED_ABSOLUTE_WEIGHTS:
        key = f"fixed_{_fixed_suffix(value)}_ratio"
        if key in row:
            checks.append((key, ratio_from_row(row, value), float(row[key])))
    maximum = 0.0
    for name, reconstructed, runtime in checks:
        error = abs(reconstructed - runtime)
        maximum = max(maximum, error)
        if error > tolerance:
            raise CalibrationError(
                f"metric parity failed for target step {row.get('target_step_id')} "
                f"field={name}: reconstructed={reconstructed:.12g} "
                f"runtime={runtime:.12g} abs_error={error:.3g} "
                f"tolerance={tolerance:.3g}"
            )
    return maximum


def validate_block(block: dict[str, Any]) -> dict[str, Any]:
    if int(block.get("schema_version", -1)) != SCHEMA_VERSION:
        raise CalibrationError(
            f"unsupported calibration schema {block.get('schema_version')!r}"
        )
    if block.get("kind") != "spectrum_h3_replay_calibration":
        raise CalibrationError("input JSON is not a Spectrum replay calibration block")
    rows = block.get("target_rows")
    if not isinstance(rows, list) or not rows:
        raise CalibrationError("calibration block has no target_rows")
    metadata = block.get("metadata") or {}
    if metadata.get("compatible") is False:
        raise CalibrationError("runtime marked calibration block incompatible")
    tolerance = float(metadata.get("parity_tolerance", DEFAULT_PARITY_TOLERANCE))
    if not math.isfinite(tolerance) or tolerance <= 0.0:
        raise CalibrationError("invalid parity tolerance")
    max_error = 0.0
    trace = (block.get("provenance") or {}).get("trace_fingerprint")
    if not isinstance(trace, str) or not trace:
        raise CalibrationError("calibration block has no trace_fingerprint")
    for row in rows:
        if not isinstance(row, dict):
            raise CalibrationError("target_rows must contain JSON objects")
        if int(row.get("schema_version", -1)) != SCHEMA_VERSION:
            raise CalibrationError("row schema version does not match block schema")
        if row.get("trace_fingerprint") != trace:
            raise CalibrationError("row trace_fingerprint does not match block provenance")
        max_error = max(
            max_error,
            validate_row_parity(row, tolerance=tolerance),
        )
    return {
        "rows": len(rows),
        "parity_tolerance": tolerance,
        "max_parity_abs_error": max_error,
    }


def _extract_json_objects_from_log(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    blocks: list[dict[str, Any]] = []
    offset = 0
    while True:
        marker = text.find(LOG_PREFIX, offset)
        if marker < 0:
            break
        start = marker + len(LOG_PREFIX)
        try:
            value, consumed = decoder.raw_decode(text[start:])
        except json.JSONDecodeError as exc:
            raise CalibrationError(
                f"malformed calibration JSON after log marker at byte {marker}"
            ) from exc
        if isinstance(value, dict):
            blocks.append(value)
        offset = start + consumed
    return blocks


def parse_calibration_text(text: str) -> list[dict[str, Any]]:
    stripped = text.strip()
    direct: Any = None
    if stripped:
        try:
            direct = json.loads(stripped)
        except json.JSONDecodeError:
            direct = None
    if isinstance(direct, dict):
        if direct.get("kind") == "spectrum_h3_replay_calibration":
            return [direct]
        if isinstance(direct.get("calibration_blocks"), list):
            return [item for item in direct["calibration_blocks"] if isinstance(item, dict)]
    if isinstance(direct, list):
        return [
            item
            for item in direct
            if isinstance(item, dict)
            and item.get("kind") == "spectrum_h3_replay_calibration"
        ]
    return _extract_json_objects_from_log(text)


def _parse_annotation_specs(
    specs: list[str],
    inputs: list[str],
    *,
    kind: str,
) -> dict[str, str]:
    known = {str(pathlib.Path(item)) for item in inputs}
    resolved: dict[str, str] = {}
    for spec in specs:
        if "=" in spec:
            key, value = spec.split("=", 1)
            if not key or not value:
                raise CalibrationError(f"invalid --{kind} annotation {spec!r}")
            normalized = str(pathlib.Path(key))
            if normalized not in known:
                raise CalibrationError(
                    f"--{kind} annotation {key!r} matches no input"
                )
            resolved[normalized] = value
        else:
            if len(inputs) != 1:
                raise CalibrationError(
                    f"bare --{kind} requires exactly one input; use INPUT=VALUE with multiple inputs"
                )
            resolved[str(pathlib.Path(inputs[0]))] = spec
    return resolved


def _annotation_seed(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise CalibrationError(f"invalid seed annotation {value!r}")
    try:
        converted = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CalibrationError(f"invalid seed annotation {value!r}") from exc
    try:
        if converted != value and str(converted) != str(value):
            raise CalibrationError(f"invalid seed annotation {value!r}")
    except (TypeError, ValueError) as exc:
        raise CalibrationError(f"invalid seed annotation {value!r}") from exc
    return converted


def _validate_run_collection(runs: list[RunBlock]) -> None:
    labels: set[str] = set()
    identities: set[str] = set()
    for run in runs:
        if run.label in labels:
            raise CalibrationError(
                f"duplicate run label {run.label!r}; use --label to make folds unambiguous"
            )
        labels.add(run.label)
        identity = run.analysis_identity
        if identity in identities:
            raise CalibrationError(
                "duplicate calibration run identity; refusing to count the same trace "
                f"twice as independent evidence: {identity}"
            )
        identities.add(identity)


def load_runs(
    inputs: list[str],
    *,
    label_specs: list[str] | None = None,
    seed_specs: list[str] | None = None,
) -> list[RunBlock]:
    labels = _parse_annotation_specs(label_specs or [], inputs, kind="label")
    seeds = _parse_annotation_specs(seed_specs or [], inputs, kind="seed")
    runs: list[RunBlock] = []
    for input_name in inputs:
        path = pathlib.Path(input_name)
        key = str(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise CalibrationError(f"cannot read {path}: {exc}") from exc
        blocks = parse_calibration_text(text)
        if not blocks:
            raise CalibrationError(f"no calibration block found in {path}")
        for block_index, block in enumerate(blocks):
            validate_block(block)
            provenance = block.get("provenance") or {}
            runtime_label = provenance.get("label")
            runtime_seed = provenance.get("seed")
            requested_label = labels.get(key) or runtime_label or path.name
            label = (
                str(requested_label)
                if len(blocks) == 1
                else f"{requested_label}#{block_index + 1}"
            )
            annotated_seed = _annotation_seed(seeds.get(key))
            runtime_seed_value = _annotation_seed(runtime_seed)
            if (
                annotated_seed is not None
                and runtime_seed_value is not None
                and annotated_seed != runtime_seed_value
            ):
                raise CalibrationError(
                    f"seed annotation {annotated_seed} conflicts with runtime seed "
                    f"{runtime_seed_value} for {path}"
                )
            seed_value = (
                annotated_seed if annotated_seed is not None else runtime_seed_value
            )
            runs.append(
                RunBlock(
                    source=key,
                    block_index=block_index,
                    label=label,
                    seed=seed_value,
                    block=block,
                )
            )
    _validate_run_collection(runs)
    return runs


def _mean(values: Iterable[float]) -> float:
    items = [float(value) for value in values]
    return sum(items) / len(items) if items else 0.0


def _pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mx = _mean(xs)
    my = _mean(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    numerator = sum(x * y for x, y in zip(dx, dy, strict=True))
    denominator = math.sqrt(sum(x * x for x in dx) * sum(y * y for y in dy))
    if denominator <= 1e-12:
        return 0.0
    return max(-1.0, min(1.0, numerator / denominator))


def residual_bucket(correlation: float) -> str:
    magnitude = abs(float(correlation))
    if magnitude < 0.5:
        return "weak"
    if magnitude < 0.6:
        return "indeterminate/noise-floor"
    return "candidate-structure"


def _metrics(rows: list[dict[str, Any]], weights: list[float]) -> dict[str, float | bool]:
    if len(rows) != len(weights) or not rows:
        raise CalibrationError("metrics require one predicted weight per target row")
    candidate = [ratio_from_row(row, weight) for row, weight in zip(rows, weights, strict=True)]
    local = [float(row["local_ratio"]) for row in rows]
    current = [float(row["current_ratio"]) for row in rows]
    oracle = [float(row["oracle_ratio"]) for row in rows]
    oracle_weights = [float(row["oracle_weight"]) for row in rows]
    predicted = [clamp_weight(weight) for weight in weights]
    errors = [p - o for p, o in zip(predicted, oracle_weights, strict=True)]
    mean_local = _mean(local)
    mean_candidate = _mean(candidate)
    mean_current = _mean(current)
    mean_oracle = _mean(oracle)
    denominator = mean_local - mean_oracle
    headroom_evaluable = denominator > 1e-12
    headroom = (mean_local - mean_candidate) / denominator if headroom_evaluable else 0.0
    return {
        "ratio_mean": mean_candidate,
        "advantage_vs_local_mean": _mean(
            (l - c) / max(l, 1e-12)
            for l, c in zip(local, candidate, strict=True)
        ),
        "advantage_vs_current_mean": _mean(
            (cur - c) / max(cur, 1e-12)
            for cur, c in zip(current, candidate, strict=True)
        ),
        "local_ratio_mean": mean_local,
        "current_ratio_mean": mean_current,
        "oracle_ratio_mean": mean_oracle,
        "headroom_capture_evaluable": headroom_evaluable,
        "headroom_capture": headroom,
        "weight_mae": _mean(abs(error) for error in errors),
        "weight_rmse": math.sqrt(_mean(error * error for error in errors)),
        "weight_bias": _mean(errors),
    }


def _solve_linear_system(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    n = len(rhs)
    augmented = [list(matrix[i]) + [float(rhs[i])] for i in range(n)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= 1e-15:
            raise CalibrationError("calibration fit is singular after fixed ridge")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        for row in range(n):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor == 0.0:
                continue
            augmented[row] = [
                left - factor * right
                for left, right in zip(
                    augmented[row], augmented[column], strict=True
                )
            ]
    return [augmented[row][-1] for row in range(n)]


def fit_quadratic_linear(
    rows: list[dict[str, Any]],
    *,
    extra_predictor: str | None,
) -> tuple[list[str], list[float]]:
    if not rows:
        raise CalibrationError("cannot fit calibration model without training rows")
    names = ["intercept", "current_weight"]
    if extra_predictor is not None:
        if extra_predictor not in LEVEL2_PREDICTORS:
            raise CalibrationError(f"unsupported Level 2 predictor {extra_predictor!r}")
        names.append(extra_predictor)
    size = len(names)
    gram = [[0.0 for _ in range(size)] for _ in range(size)]
    rhs = [0.0 for _ in range(size)]
    for row in rows:
        features = [1.0, float(row["current_weight"])]
        if extra_predictor is not None:
            features.append(float(row[extra_predictor]))
        if not all(math.isfinite(value) for value in features):
            raise CalibrationError("training predictor is nonfinite")
        b = float(row["local_error_dot_spectral_delta_mean"])
        c = float(row["spectral_delta_sq_mean"])
        denominator = float(row["ratio_denominator_rms"])
        scale = 1.0 / (denominator * denominator)
        for i in range(size):
            rhs[i] += -scale * b * features[i]
            for j in range(size):
                gram[i][j] += scale * c * features[i] * features[j]
    for index in range(size):
        gram[index][index] += FIT_RIDGE
    return names, _solve_linear_system(gram, rhs)


def _raw_coefficient_dict(names: list[str], values: list[float]) -> dict[str, float]:
    return {name: float(value) for name, value in zip(names, values, strict=True)}


def predict_linear(
    rows: list[dict[str, Any]],
    names: list[str],
    coefficients: list[float],
) -> list[float]:
    predicted: list[float] = []
    for row in rows:
        value = coefficients[0]
        for name, coefficient in zip(names[1:], coefficients[1:], strict=True):
            value += coefficient * float(row[name])
        predicted.append(clamp_weight(value))
    return predicted


def _evidence_level(run_count: int) -> str:
    if run_count <= 1:
        return "NON-CONFIRMATORY / DEVELOPMENT ONLY"
    if run_count == 2:
        return "WEAK / PRELIMINARY"
    return "MULTI-RUN / GENERALIZATION TEST (NOT AUTOMATICALLY PROMOTED)"


def _folds(runs: list[RunBlock]) -> list[tuple[list[RunBlock], RunBlock, bool]]:
    if len(runs) == 1:
        return [(runs, runs[0], True)]
    folds = []
    for index, held_out in enumerate(runs):
        training = [run for i, run in enumerate(runs) if i != index]
        folds.append((training, held_out, False))
    return folds


def _concat_rows(runs: list[RunBlock]) -> list[dict[str, Any]]:
    return [row for run in runs for row in run.rows]


def _baseline_weights(rows: list[dict[str, Any]], spec: ModelSpec) -> list[float]:
    if spec.name == "local":
        return [0.0 for _ in rows]
    if spec.name == "current":
        return [float(row["current_weight"]) for row in rows]
    if spec.name.startswith("alpha_"):
        alpha = float(spec.name.removeprefix("alpha_").replace("p", "."))
        return [alpha * float(row["current_weight"]) for row in rows]
    raise CalibrationError(f"unknown baseline {spec.name}")


def _metric_delta(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, float]:
    denominator = float(candidate["local_ratio_mean"]) - float(candidate["oracle_ratio_mean"])
    incremental_headroom = (
        (float(baseline["ratio_mean"]) - float(candidate["ratio_mean"])) / denominator
        if denominator > 1e-12
        else 0.0
    )
    return {
        "ratio_mean_delta": float(candidate["ratio_mean"]) - float(baseline["ratio_mean"]),
        "headroom_capture_delta": float(candidate["headroom_capture"]) - float(baseline["headroom_capture"]),
        "weight_mae_delta": float(candidate["weight_mae"]) - float(baseline["weight_mae"]),
        "weight_rmse_delta": float(candidate["weight_rmse"]) - float(baseline["weight_rmse"]),
        "weight_bias_delta": float(candidate["weight_bias"]) - float(baseline["weight_bias"]),
        "abs_weight_bias_delta": abs(float(candidate["weight_bias"])) - abs(float(baseline["weight_bias"])),
        "incremental_headroom_over_baseline": incremental_headroom,
    }


def _residual_report(runs: list[RunBlock]) -> dict[str, Any]:
    predictors = ("current_weight", *LEVEL2_PREDICTORS)
    per_run: list[dict[str, Any]] = []
    for run in runs:
        oracle = [float(row["oracle_weight"]) for row in run.rows]
        predicted = [0.5 * float(row["current_weight"]) for row in run.rows]
        residual = [o - p for o, p in zip(oracle, predicted, strict=True)]
        correlations = {}
        for predictor in predictors:
            values = [float(row[predictor]) for row in run.rows]
            correlation = _pearson(values, residual)
            correlations[predictor] = {
                "r": correlation,
                "interpretation": residual_bucket(correlation),
            }
        per_run.append({"run": run.label, "n": len(run.rows), "correlations": correlations})
    replicated = []
    if len(runs) >= 2:
        for predictor in predictors:
            values = [entry["correlations"][predictor]["r"] for entry in per_run]
            strong = [value for value in values if abs(value) >= 0.6]
            same_positive = len(strong) >= 2 and all(value > 0 for value in strong)
            same_negative = len(strong) >= 2 and all(value < 0 for value in strong)
            if same_positive or same_negative:
                replicated.append(
                    {
                        "predictor": predictor,
                        "sign": "positive" if strong[0] > 0 else "negative",
                        "qualifying_runs": len(strong),
                    }
                )
    return {
        "interpretation": (
            "n≈11 sequential trajectory rows per run; |r|>=0.6 is candidate structure, "
            "not formal significance; same-sign cross-run replication is required"
        ),
        "per_run": per_run,
        "replicated_same_sign_abs_r_ge_0p6": replicated,
    }


def analyze_runs(runs: list[RunBlock]) -> dict[str, Any]:
    if not runs:
        raise CalibrationError("at least one calibration run is required")
    _validate_run_collection(runs)
    evidence = _evidence_level(len(runs))
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "evidence_level": evidence,
        "run_count": len(runs),
        "fit_objective": (
            "training-only unweighted mean of per-target squared hidden-feature ratios "
            "using exact quadratic moments before clipping; no feature normalization; "
            f"fixed ridge={FIT_RIDGE:g}; final weights clipped to [0,1]"
        ),
        "aggregate_weighting": "per-target across held-out complete runs",
        "runs": [
            {
                "label": run.label,
                "source": run.source,
                "block_index": run.block_index,
                "seed": run.seed,
                "runtime_seed": run.runtime_seed,
                "trace_fingerprint": run.trace_fingerprint,
                "analysis_identity": run.analysis_identity,
                "rows": len(run.rows),
            }
            for run in runs
        ],
        "level0": {},
        "level1": {},
        "level2": {},
        "residual_structure_alpha_0p50": _residual_report(runs),
    }

    all_rows = _concat_rows(runs)
    level0_specs = [
        ModelSpec("local", 0),
        ModelSpec("current", 0),
        *[
            ModelSpec(f"alpha_{_fixed_suffix(alpha)}", 0)
            for alpha in FIXED_ALPHAS
        ],
    ]
    for spec in level0_specs:
        per_run = []
        all_weights = []
        for run in runs:
            weights = _baseline_weights(run.rows, spec)
            all_weights.extend(weights)
            per_run.append({"run": run.label, "metrics": _metrics(run.rows, weights)})
        report["level0"][spec.name] = {
            "per_run": per_run,
            "aggregate": _metrics(all_rows, all_weights),
        }

    fold_level1: dict[str, dict[str, Any]] = {}
    level1_all_rows: list[dict[str, Any]] = []
    level1_all_weights: list[float] = []
    level1_folds = []
    for training_runs, held_out, in_sample in _folds(runs):
        train_rows = _concat_rows(training_runs)
        names, coefficients = fit_quadratic_linear(train_rows, extra_predictor=None)
        weights = predict_linear(held_out.rows, names, coefficients)
        metrics = _metrics(held_out.rows, weights)
        fold = {
            "held_out_run": held_out.label,
            "training_runs": [run.label for run in training_runs],
            "in_sample_development": in_sample,
            "coefficients": _raw_coefficient_dict(names, coefficients),
            "metrics": metrics,
        }
        level1_folds.append(fold)
        fold_level1[held_out.label] = fold
        level1_all_rows.extend(held_out.rows)
        level1_all_weights.extend(weights)
    report["level1"]["affine_current_weight"] = {
        "formula": "clip(a + b*current_weight, 0, 1)",
        "folds": level1_folds,
        "aggregate_held_out": _metrics(level1_all_rows, level1_all_weights),
    }

    level2_fold_cache: dict[str, dict[str, dict[str, Any]]] = {}
    for predictor in LEVEL2_PREDICTORS:
        folds_for_predictor = []
        fold_cache = {}
        aggregate_rows: list[dict[str, Any]] = []
        aggregate_weights: list[float] = []
        for training_runs, held_out, in_sample in _folds(runs):
            train_rows = _concat_rows(training_runs)
            names, coefficients = fit_quadratic_linear(
                train_rows,
                extra_predictor=predictor,
            )
            weights = predict_linear(held_out.rows, names, coefficients)
            metrics = _metrics(held_out.rows, weights)
            level1_metrics = fold_level1[held_out.label]["metrics"]
            fold = {
                "held_out_run": held_out.label,
                "training_runs": [run.label for run in training_runs],
                "in_sample_development": in_sample,
                "coefficients": _raw_coefficient_dict(names, coefficients),
                "metrics": metrics,
                "vs_level1": _metric_delta(metrics, level1_metrics),
            }
            folds_for_predictor.append(fold)
            fold_cache[held_out.label] = fold
            aggregate_rows.extend(held_out.rows)
            aggregate_weights.extend(weights)
        aggregate = _metrics(aggregate_rows, aggregate_weights)
        level1_aggregate = report["level1"]["affine_current_weight"]["aggregate_held_out"]
        report["level2"][predictor] = {
            "formula": f"clip(a + b*current_weight + c*{predictor}, 0, 1)",
            "folds": folds_for_predictor,
            "aggregate_held_out": aggregate,
            "vs_level1_aggregate": _metric_delta(aggregate, level1_aggregate),
        }
        level2_fold_cache[predictor] = fold_cache

    coordinate_folds = level2_fold_cache["coordinate"]
    coordinate_aggregate = report["level2"]["coordinate"]["aggregate_held_out"]
    for predictor in LEVEL2_PREDICTORS:
        if predictor == "coordinate":
            continue
        for fold in report["level2"][predictor]["folds"]:
            coordinate_metrics = coordinate_folds[fold["held_out_run"]]["metrics"]
            fold["vs_coordinate_control"] = _metric_delta(
                fold["metrics"],
                coordinate_metrics,
            )
        report["level2"][predictor]["vs_coordinate_control_aggregate"] = _metric_delta(
            report["level2"][predictor]["aggregate_held_out"],
            coordinate_aggregate,
        )

    return report


def render_text(report: dict[str, Any]) -> str:
    lines = [
        f"Evidence: {report['evidence_level']}",
        f"Runs: {report['run_count']}",
        f"Fit: {report['fit_objective']}",
        f"Aggregate weighting: {report['aggregate_weighting']}",
        "",
        "Level 0 baselines",
    ]
    for name, entry in report["level0"].items():
        metrics = entry["aggregate"]
        lines.append(
            f"  {name}: ratio={metrics['ratio_mean']:.6f} "
            f"headroom={metrics['headroom_capture']:.6f} "
            f"MAE={metrics['weight_mae']:.6f} RMSE={metrics['weight_rmse']:.6f} "
            f"bias={metrics['weight_bias']:+.6f}"
        )
    lines.extend(("", "Level 1: affine current weight"))
    for fold in report["level1"]["affine_current_weight"]["folds"]:
        lines.append(
            f"  holdout={fold['held_out_run']} coeff={fold['coefficients']} "
            f"ratio={fold['metrics']['ratio_mean']:.6f}"
        )
    lines.extend(("", "Level 2: current weight + one predictor"))
    for predictor, entry in report["level2"].items():
        metrics = entry["aggregate_held_out"]
        delta = entry["vs_level1_aggregate"]
        text = (
            f"  {predictor}: ratio={metrics['ratio_mean']:.6f} "
            f"delta_vs_L1={delta['ratio_mean_delta']:+.6f} "
            f"incremental_headroom_vs_L1={delta['incremental_headroom_over_baseline']:+.6f}"
        )
        if predictor != "coordinate":
            coordinate = entry["vs_coordinate_control_aggregate"]
            text += f" delta_vs_coordinate={coordinate['ratio_mean_delta']:+.6f}"
        lines.append(text)
        for fold in entry["folds"]:
            lines.append(
                f"    holdout={fold['held_out_run']} coeff={fold['coefficients']} "
                f"ratio={fold['metrics']['ratio_mean']:.6f} "
                f"vs_L1={fold['vs_level1']['ratio_mean_delta']:+.6f}"
            )
    lines.extend(("", "Alpha=.5 residual correlations by complete run"))
    for entry in report["residual_structure_alpha_0p50"]["per_run"]:
        lines.append(f"  {entry['run']} (n={entry['n']}):")
        for predictor, item in entry["correlations"].items():
            lines.append(
                f"    {predictor}: r={item['r']:+.6f} ({item['interpretation']})"
            )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze Spectrum MiniMax-H3 replay calibration blocks without ComfyUI, "
            "model loading, or GPU use. Whole calibration blocks/runs are the CV unit."
        )
    )
    parser.add_argument("inputs", nargs="+", help="Calibration JSON files or full ComfyUI logs")
    parser.add_argument(
        "--label",
        action="append",
        default=[],
        metavar="[INPUT=]LABEL",
        help="Annotate a run label; INPUT=VALUE is required with multiple inputs",
    )
    parser.add_argument(
        "--seed",
        action="append",
        default=[],
        metavar="[INPUT=]SEED",
        help=(
            "Annotate a seed only when runtime provenance is unavailable; a conflicting "
            "runtime seed is rejected. INPUT=VALUE is required with multiple inputs"
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit deterministic JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        runs = load_runs(args.inputs, label_specs=args.label, seed_specs=args.seed)
        report = analyze_runs(runs)
    except CalibrationError as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
