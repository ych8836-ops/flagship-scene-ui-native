# Forecast trust and replay calibration benchmark record

This document records the forecast-quality investigation following PR #39 and the finalization work in PR #45. Hidden-feature ratios and advantages are feature-space error measurements. They are not perceptual-quality percentages.

## Final research state

### Supported

- The causal PR #39 generic latest-delta correction remains part of `model_aware_mode=full`.
- In current controlled native ER-SDE testing, `model_aware_mode=full` in single-pass mode is the preferred tested model-aware quality configuration among the compared modes.
- The correction itself adds zero transformer evaluations.

### Supported alternative

- Offline smoothing replay remains supported. It has historical same-seed evidence for fixing important MiniMax H3 audio/stutter/distortion behavior and remains the compatibility-safe global default.
- Current native ER-SDE testing found a temporal facial case where `full` single-pass performed better than the tested replay path. This result is scoped to native ER-SDE.

### Default off / not recommended for promotion

```text
model_aware_trust_shrinkage = false
```

Causal trust shrinkage produced large hidden-feature observer improvements. Repeated real perceptual A/B testing did not produce a reliable user-facing gain and sometimes slightly favored trust disabled. The user-facing gate is complete. No further kappa tuning or denser trust search is planned for this cycle. The setting remains available for research/reproduction and saved-workflow compatibility.

### Rejected transfers

```text
causal trust kappa -> future-bracket replay
causal PR #39 latest-delta scalar -> future-bracket replay direction
```

The supported replay-generic-correction default is:

```text
model_aware_replay_generic_correction = false
```

`true` remains a legacy/scientific-ablation path only.

### Research infrastructure only

- exact VIDEO replay calibration export;
- per-target quadratic moments and exact ratio normalization;
- provenance/config/schedule/topology/trace fingerprints;
- standard-library CPU evaluator;
- whole-run cross-validation;
- Level 0 fixed controls, Level 1 affine current-weight baseline, and one-predictor Level 2 residual tests.

No applied replay controller is introduced by this research.

### Closed hypotheses

- pure global alpha as a complete replay solution;
- K=2 correction;
- FinalLayer-transformed correction;
- previous-error direction families;
- hold-anchor replay shrinkage;
- causal kappa transfer to replay;
- causal generic scalar transfer to replay.

## Final controlled native ER-SDE quality gate

All three runs below used the same seed, prompt, starting image, resolution, duration/frame count, native ER-SDE sampler/scheduler setup, model, precision, workflow, and remaining generation settings. Telemetry paths that omit the seed do not change the controlled paired nature of the runs.

These conclusions apply to native ER-SDE under the tested H3 configuration. Euler, RES/RES CFG++, Turbo/LightX2V, and other samplers remain outside this perceptual conclusion.

### `schedule_confidence`, single pass

```text
sampler = sample_er_sde
steps = 20
model_aware_mode = schedule_confidence
offline_smoothing_replay = false
model_aware_trust_shrinkage = false

actual_steps = 11
forecast_steps = 9
actual_transformer_calls = 11
fallbacks = 0
model_aware_extra_nfes = 0

model_aware_correction_max = 0
model_aware_causal_correction_s = 0

audio hidden forecast ratio = 1.789477
video hidden forecast ratio = 1.309651
```

Perceptual observation: a subtle abnormal/false eye movement remained shortly before the intended eye closure. The defect was much smaller than older Spectrum artifacts and still visible in direct comparison.

### `full`, single pass

The expensive schedule was identical:

```text
actual_steps = 11
forecast_steps = 9
actual_transformer_calls = 11
fallbacks = 0
model_aware_extra_nfes = 0
```

The meaningful additional mechanism over `schedule_confidence` is the retained generic latest-delta causal correction.

```text
audio raw       = 1.777636
audio corrected = 1.670690
hidden-error reduction ~= 6.02%

video raw       = 1.313055
video corrected = 1.250087
hidden-error reduction ~= 4.80%

model_aware_correction_max = 0.148827
model_aware_causal_correction_s = 0.000381
model_aware_extra_nfes = 0
```

Representative later video anchors moved consistently in the improving direction:

```text
1.233778 -> 1.166099
1.278252 -> 1.200908
1.391828 -> 1.307558
1.392824 -> 1.316612
1.153456 -> 1.103306
```

Audio showed the same consistent correction direction.

Perceptual result: the recurring false eye-motion artifact was absent. Eye motion remained synchronized with the intended actual eye-closing motion instead of visibly moving incorrectly immediately before the closure.

This gives aligned evidence from three independent dimensions of the same controlled run pair:

```text
lower hidden forecast error
same transformer NFE
removal of a concrete temporal facial artifact
```

The 6.02% and 4.80% figures describe hidden-feature error on this trace only. They are not perceptual improvement percentages.

### Offline smoothing replay

Comparison configuration:

```text
model_aware_mode = off
offline_smoothing_replay = true
```

First pass:

```text
actual_steps = 11
forecast_steps = 9
actual_transformer_calls = 11
```

Replay:

```text
offline_replay_steps = 20
anchor_steps = 11
smoothed_steps = 9
replay transformer calls = 0
replay wall time ~= 13.25 s
archive ~= 4315.5 MiB
effective video blend mean ~= 0.346053
audio = local-only
```

Perceptual result: clearly visible abnormal eye motion remained before the intended closure. It was more visible than in `schedule_confidence` and clearly more visible than in `full` for this artifact.

This is a scoped ER-SDE result. Offline replay retains its historical audio rationale and supported status.

### Plain/base Spectrum was not part of this triplet

No result for plain/base Spectrum is recorded for this exact three-run eye-motion comparison. Suspected behavior from older runs is not treated as measured evidence here.

## Supporting native ER-SDE pronunciation evidence

An earlier same-seed ER-SDE comparison contained the German sentence:

```text
meine Freunde sind noch 2 Stunden weg
```

The base/schedule-confidence-like path pronounced `weg` incorrectly, closer to the noun pronunciation sometimes rendered informally as "Wehg". Both `full` and offline replay produced the intended pronunciation, approximately "weck" in this context. A direct follow-up isolation found `schedule_confidence` sounding like base Spectrum and `full` retaining the corrected pronunciation.

This supports attribution to the generic causal correction rather than Feature-2 confidence scheduling alone. It remains native-ER-SDE perceptual evidence, not a universal speech-quality claim.

## Main geometry finding

> Parameters or directions calibrated for one forecast geometry cannot be assumed to transfer to a different endpoint geometry.

PR #45 produced two independent examples.

### Causal trust kappa -> future-bracket replay

Causal trust is calibrated between the latest exact causal anchor and a causal forecast. The rejected replay transfer interpolated between a stale causal hold and a future-bracketed replay proposal. Replay-native leave-one-out evaluation selected `kappa=1.0` throughout the scored audio/video replay targets. Full replay retention was optimal in those traces; movement toward the stale causal hold increased hidden error.

RACER Proposition 2 establishes that the MSE-optimal interpolation coefficient depends on endpoint error statistics and correlation. That supports endpoint-geometry dependence in principle. RACER does not analyze Spectrum H3's future-bracket replay construction; the replay result here is empirical.

### Causal PR #39 latest-delta scalar -> future replay bracket direction

PR #39 remains supported in the geometry in which its scalar was learned:

```text
d_causal = latest_exact - previous_exact
```

Offline replay had historically transplanted the same scalar onto:

```text
d_replay = right_future_bracket_anchor - left_future_bracket_anchor
```

Across independent 25-step trace geometries, the persisted causal scalar was negative, useful replay-native projections were positive, the causal/replay direction cosine was approximately zero or negative, and applying the causal scalar in replay increased hidden reconstruction error.

The causal mechanism remains supported. The future-bracket transfer is rejected.

## Replay generic correction: closed, default disabled

The predeclared closure criterion is satisfied:

- hidden-feature rejection of causal-scalar -> future-bracket replay transfer replicated across independent trace geometries;
- two same-pair perceptual comparisons judged correction-disabled replay non-worse/indistinguishable.

Therefore:

```text
model_aware_replay_generic_correction = false   # supported default
model_aware_replay_generic_correction = true    # explicit legacy/reproduction ablation
```

`false` suppresses only the transplanted replay scalar. The causal PR #39 latest-delta correction remains unchanged. Validation attenuation, local/spectral blending, scheduling, exact anchors, transformer NFE, and sampler refresh rules remain unchanged.

## Trace identity and provenance discipline

Historical traces keep geometry-based identities when seed/config provenance was not logged. Known distinct geometries include:

```text
trace_37905_57x70x38_t927
  target_video_rows = 37905
  video_shape       = (1, 24, 57, 70, 38)
  text_length       = 927

trace_37620_57x60x44_t922
  target_video_rows = 37620
  video_shape       = (1, 24, 57, 60, 44)
  text_length       = 922
```

New calibration exports capture the ComfyUI `OUTER_SAMPLE` seed when it is cleanly observable as an integral value. Missing seed provenance remains `null`. The offline evaluator accepts explicit external `--seed` and `--label` annotations.

## Pure multiplicative alpha: useful baseline, rejected complete solution

The alpha-capable development trace `trace_37620_57x60x44_t922` reported:

```text
local ratio       0.730744
current ratio     0.734151
oracle ratio      0.721140
```

Predeclared alpha sweep:

```text
alpha 0.00    ratio 0.730744    headroom capture   0.000%
alpha 0.25    ratio 0.726611    headroom capture  43.039%
alpha 0.50    ratio 0.725793    headroom capture  51.553%
alpha 0.75    ratio 0.728315    headroom capture  25.294%
alpha 1.00    ratio 0.734151    headroom capture -35.476%
```

Best predeclared alpha was `0.50`. Its oracle-weight error was:

```text
MAE   0.090482
RMSE  0.100304
bias -0.000126
```

The predeclared complete-solution requirement was at least 60% oracle-vs-local headroom capture. The best alpha reached 51.553% on its development trace.

Pure global alpha remains a calibration baseline and is closed as a complete replay solution. No denser alpha search or applied alpha control is planned.

## Residual structure after alpha=.5

On `trace_37620_57x60x44_t922`:

```text
residual vs causal disagreement      +0.922956
residual vs validation penalty       -0.795547
residual vs spectral gap             +0.661601
residual vs coordinate               +0.816378
residual vs current weight           +0.835505
```

The floor diagnostic was partial:

```text
oracle-near-zero targets               2 / 11 = 18.18%
current weight there                    0.227179
alpha=.5 weight there                   0.113590
share of alpha=.5 MAE                  22.825%
share of alpha=.5 squared error        23.685%
```

These `n=11` sequential trajectory correlations are exploratory diagnostics. No disagreement, coordinate, validation-penalty, floor, interaction, tree, neural, or AutoML runtime controller is authorized from them.

## Exact per-target VIDEO replay calibration dataset

PR #45 exports a compact machine-readable VIDEO replay calibration block under existing `debug=true` research logging for `model_aware_mode=full` with offline replay.

```text
SPECTRUM_REPLAY_CALIBRATION_JSON={...}
```

The block contains bounded scalar metadata and `target_rows[]`. No hidden-feature tensor or raw feature array is serialized.

### Authoritative quadratic representation

Sign convention:

```text
e = local - withheld_target
d = spectral - local

A = local_error_sq_mean
  = mean(e^2)

B = local_error_dot_spectral_delta_mean
  = mean(e * d)

C = spectral_delta_sq_mean
  = mean(d^2)

candidate_mse(w) = A + 2*w*B + w^2*C
w_oracle = clamp(-B / max(C, ratio_epsilon^2), 0, 1)
```

### Exact ratio normalization

Runtime parity is preserved as:

```text
actual_rms = sqrt(mean(actual^2))
ratio_epsilon = max(actual_rms * 1e-6, float32_epsilon)

hold_error_sq_mean = mean((actual - hold)^2)
ratio_denominator_rms = max(sqrt(hold_error_sq_mean), ratio_epsilon)

ratio(w) = sqrt(candidate_mse(w)) / ratio_denominator_rms
```

Aggregate reporting is the mean of per-target ratios. It is not a pooled global RMS.

Serialized moments reconstruct runtime local/current/full-spectral/fixed-control/oracle values within the declared parity tolerance (`2e-5`). Structurally invalid or non-interior withheld targets are rejected before bracket indexing.

### Calibration row schema

Identity/geometry:

```text
schema_version
run_id
trace_fingerprint
target_step_id
target_anchor_index
coordinate
left_anchor_step_id
left_anchor_index
right_anchor_step_id
right_anchor_index
bracket_coordinate_spacing
bracket_fraction
target_video_rows
scoring_sample_count
```

Quadratic/normalization:

```text
local_error_sq_mean
spectral_delta_sq_mean
local_error_dot_spectral_delta_mean
hold_error_sq_mean
ratio_epsilon
ratio_denominator_rms
```

Deployable pre-target predictors:

```text
current_weight
causal_disagreement
validation_penalty
spectral_gap
coordinate
```

Post-target labels/parity:

```text
oracle_weight
required_adjustment
local_ratio
current_ratio
full_spectral_ratio
oracle_ratio
fixed_0p00_ratio
fixed_0p25_ratio
fixed_0p50_ratio
fixed_0p75_ratio
fixed_1p00_ratio
current_axis_ratio
moment_oracle_weight
moment_oracle_ratio
max_parity_abs_error
row_compatible
```

Predictor construction completes before the withheld target is read. The withheld target is then used only for moments, errors, oracle labels, and evaluation values. Production replay consumes no oracle field.

### Provenance and fingerprints

Block provenance includes:

```text
package_name
package_version
source_schema_revision
source_revision
source_revision_source
seed
label
config_hash
schedule_fingerprint
topology_fingerprint
trace_fingerprint
```

`config_hash` is SHA-256 over canonical JSON for the complete Spectrum configuration plus sampler, step count, and available scheduler metadata. `schedule_fingerprint` covers the complete archive sequence of `(step_id, coordinate, actual)`. `topology_fingerprint` covers the available native H3 topology/configuration identity. `trace_fingerprint` combines source/schema identity, seed when available, config, schedule, topology, and pre-target signatures. Oracle/post-target values are excluded.

No hot-path Git subprocess or `.git` dependency exists.

## Offline multi-run evaluator

Tool:

```text
tools/analyze_replay_calibration.py
```

It is standard-library/CPU-only and starts neither ComfyUI nor a model/GPU runtime. It accepts direct calibration JSON or full ComfyUI logs containing the marker. Each calibration block is one run; target rows are never randomized across train/test folds.

### Level 0: fixed/known baselines

```text
local:    w=0
current:  w=current_weight
alpha:    w=alpha*current_weight
          alpha in {0,.25,.50,.75,1}
```

### Level 1: affine current-weight recalibration

```text
w_hat = clamp(a + b*current_weight, 0, 1)
```

This is the mandatory baseline for any residual-predictor claim.

### Level 2: current weight + one residual predictor

Separately:

```text
w_hat = clamp(a + b*current_weight + c*predictor, 0, 1)
```

for:

```text
causal_disagreement
validation_penalty
spectral_gap
coordinate
```

Coordinate is the explicit confound/control. No combined multi-predictor model, interaction, polynomial, threshold search, tree, neural network, or AutoML path is implemented.

### Fitting objective

Level 1/2 minimize the unweighted mean of per-target squared normalized hidden-feature error from exact training-run moments before final `[0,1]` clipping:

```text
q_i = 1 / ratio_denominator_rms_i^2
L = mean_i q_i * (A_i + 2*B_i*w_i + C_i*w_i^2)
w_i = x_i^T beta

sum(q*C*x*x^T) beta = -sum(q*B*x)
```

A fixed `1e-8` numerical ridge stabilizes the solve. There is no hyperparameter sweep and no predictor normalization.

### Whole-run validation labels

```text
1 run  -> in-sample exploratory only
          NON-CONFIRMATORY / DEVELOPMENT ONLY

2 runs -> leave-one-run-out
          WEAK / PRELIMINARY

>=3    -> leave-one-run-out over complete trajectories
          MULTI-RUN / GENERALIZATION TEST
```

Held-out runs cannot influence coefficients, normalization, regularization, or model selection. A Level 2 predictor must improve held-out results over Level 1 affine current-weight calibration. Non-coordinate Level 2 candidates also require comparison with coordinate control.

The evaluator remains research tooling. No runtime affine or residual controller is shipped from these results.

## Historical exact-calibration compatibility

```text
trace_37905_57x70x38_t927: NO
trace_37620_57x60x44_t922: NO
```

Both traces predate the exact per-target quadratic-moment schema. Their aggregate historical evidence remains valid; missing moments are not synthesized for fitted offline evaluation.

## Implementation boundaries

- trust shrinkage default remains false;
- replay generic correction default remains false;
- no causal-kappa replay transfer;
- no new affine/trust/replay controller;
- no zero/floor gate;
- no extra transformer NFE from generic correction or research telemetry;
- no retained calibration feature tensors;
- calibration export remains debug/research-only and scalar;
- ordinary calibration-diagnostic failures are isolated; CUDA OOM propagates;
- exact anchors, sampler refresh rules, and replay ownership/teardown remain authoritative.
