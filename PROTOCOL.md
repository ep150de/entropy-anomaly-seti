# Pre-Registered Protocol: A Compression-Based Anomaly Statistic for TESS Light Curves

**Version 2.0.0 — PRE-REGISTRATION, registered 2026-11-14**
**Sole author:** A. R. Lingle (independent researcher)
**Machine-readable source of truth:** `config/protocol.json` (SHA-256 recorded below; any edit invalidates every downstream catalog and result)
**Supersedes:** all Phase 1/2 detection claims, catalogs, figures and statistics in this repository.

> **Status:** No outcome data have been inspected under this protocol. Pre-registration
> intentionally precedes implementation. `pipeline/run_study_v2.py` does not exist yet;
> that is a feature, not an oversight — the parameters are frozen before anyone can tune
> them against a result.

---

## 0. Why this document exists

A first-pass referee review (2026-11-14, repo commit `7f8079e`) rejected the original
manuscript. I independently re-ran its decisive checks and they all hold:

| Referee finding | What it means | Independently confirmed |
|---|---|---|
| `K(S)=1.0733` for 150 random bytes | the zlib ratio is **container overhead**, saturated, no dynamic range | 150 random bytes → 161 bytes, exactly the reported mean_ks |
| One 8σ cadence lowers `K(S)` 1.0733→1.0533 | `μ−3σ` is a **cosmic-ray detector**, not an information detector | reproduced |
| 24 "anomalies" = 2 events | overlapping windows (W=150, stride=10) count one cadence ~15× | 14 + 10 contiguous runs, reproduced |
| `p<10⁻¹⁵`, "excess >∞" | hard-coded strings, never computed | `visualize_pleiades.py` |
| Targets are not Pleiades members | TIC 261136679 = π Men (Dec −80°); real Pleiades only in S42–44/70–71 | catalog builders use `np.random.uniform` for RA/Dec/Tmag |
| Figures from `np.random` | simulated figures presented as results | `generate_cluster_report.py`, `visualize_pleiades.py` |

The detection claim is **disproven**, not under-powered. This protocol does not try to
rescue it. It asks a narrower, falsifiable question and commits to publishing whatever
answer comes out.

---

## 1. Commitment (binding)

- The result will be written up and made public **regardless of sign**.
- A **null result is the expected primary outcome**. It is not a failure and will not be
  reframed as a detection, a "hint", or "sporadic targeted communication".
- If the null is not rejected, the deliverable is a **methods / null-result note**
  (RNAAS or equivalent): *"A compression-based anomaly statistic for TESS light curves:
  calibration, systematics, and limits."* That is a real contribution.
- No figure may contain simulated data. Figure scripts must **fail loudly** on missing
  inputs.
- Detection language and "quantum network" framing are prohibited in all outputs.

---

## 2. Hypothesis, stated so it can be false

**H0 (null).** After instrumental-systematics removal and with a calibrated complexity
estimator, the rate of low-complexity **events** in confirmed Pleiades members is
statistically indistinguishable from (a) matched field controls observed in the same
TESS sectors/cameras/CCDs and (b) phase-randomised surrogates of each target that
preserve its power spectrum, amplitude distribution and gap structure.

**H1 (alternative).** Pleiades members show an excess of low-complexity events with a
global trials-corrected `p < 0.01` **AND** the events recur in the same stars across
independent sectors **AND** they survive pixel-level vetting.

**Decision rule.** H1 is accepted **only if every one of its conditions holds
simultaneously**. Failure of any single condition ⇒ H0 stands ⇒ report as a null result /
systematics characterisation.

**Concrete signal model (fixed a priori).** A narrow-band non-natural intensity
modulation: duty cycle 0.1–0.5, bit length 0.5–4 h, depth 0.02–2%, repetition that is
*not* an integer multiple of the stellar rotation period, persisting across ≥2
independent sectors. The estimator's response to this model is fixed by injection
**before** any real-data test. Classical intensity modulation is not a quantum channel;
the no-communication theorem is acknowledged. Entanglement-based signalling is not
claimed.

The original hypothesis was unfalsifiable because any outcome (anomalies present,
absent, or appearing in controls) was absorbed as support. That constitutes the specific
defect this design removes.

---

## 3. Sample (rebuilt from real catalogs)

Built by `pipeline/build_sample_v2.py` from **Gaia DR3 + TIC v8.2**, cross-matched by
position. No synthetic coordinates, magnitudes, distances or TIC IDs. Every row carries
a `provenance` string and the exact query that produced it. The builder **raises** rather
than emitting placeholders if a service is unreachable.

- Pleiades cone: RA 56.75°, Dec +24.12°, radius 3.0°
- Parallax 6.5–8.5 mas (≈118–154 pc; true cluster ≈136 pc), `parallax_over_error > 10`
- Proper motion: pmRA 10–30, pmDec −55 to −35 mas/yr
- `RUWE < 1.4` (rejects unresolved binaries / astrometric noise)
- `Tmag < 13`, contamination ratio < 0.10
- **Blends merged within 21″ (one TESS pixel)** — duplicates such as 348639169 /
  640613235 / 640613236 become one source, not three stars
- Real observing sectors: **42, 43, 44, 70, 71** (Sector 11 was a southern pointing)
- One documented data product class for the entire analysis: SPOC 2-min PDCSAP; if
  coverage is insufficient, TESS-SPOC FFI 200 s for **all** targets and controls (never
  mixed). MAST product IDs archived per light curve.

**Controls.** Field stars from the **same sector / camera / CCD**, outside the cluster cone
and outside the parallax + proper-motion locus, matched in Tmag (±0.5 mag) and in cadence
and product. ≥5 controls per target, ≥300 total. This is the decisive comparison: same
pixels, same epoch, same instrument, differing only in cluster membership.

---

## 4. Preprocessing

| Step | Pre-registered setting | Why |
|---|---|---|
| Quality mask | `hard` (not `default`) | QLP S42 events sat on quality bit 4096 at 31% of median flux |
| Purge fraction | reported per star | reproducibility |
| Detrending | biweight time-windowed robust filter, 0.5 d | removes trends without fitting out transients |
| Outliers | 5σ per-cadence clip, 3 iterations, flagged cadences recorded | single 4–5σ cadences caused every headline anomaly |
| Windows | **time-based**, split at gaps > 0.5 d, never across the mid-sector orbit gap | index-based windows straddled BTJD 1609.70–1613.45 |
| Cadence | one product class throughout | SPOC 120 s / eleanor 1800 s / QLP 600 s were mixed freely |

---

## 5. Statistic with dynamic range

The zlib/min-max estimator is **retired**. Its values (158/159/161 bytes) were a near-binary
"does this window contain an outlier" indicator, and 161/150 = 1.0733 is zlib's stored
size for incompressible input, not entropy.

- **Primary:** normalised Lempel–Ziv complexity (LZ76) on a symbol sequence.
- **Secondary:** permutation entropy (Bandt & Pompe 2002, order 6); report the
  complexity–entropy plane (Rosso et al. 2007).
- **Symbolisation:** quantise against a **fixed per-star noise scale** (MAD of the clipped
  detrended residuals), fixed range ±5σ_star, 256 levels, out-of-range clipped.
  **Never** per-window min-max.
- Window 150 cadences; **primary stride 150 (non-overlapping)**; stride 10 retained only
  as a declared sensitivity analysis.
- **Events**, not windows: a maximal run of consecutive flagged windows = 1 event. Both
  counts are reported.

**Gate before any real data:** the estimator must show dynamic range on simulated light
curves (white, GP red noise, spotted rotator, flare, eclipsing binary). If it does not, the
method is invalid and the study stops there.

---

## 6. Null, significance, trials

- ≥**1000 IAAFT phase-randomised surrogates per star**, preserving power spectrum,
  amplitude distribution and gap structure.
- Threshold = **1st percentile of the star's own surrogate distribution**, pre-registered.
  The self-referenced `μ−3σ` cut is prohibited: it manufactures exceedances by
  construction (Student-t(5) noise gave a median of 23 "anomalies"; shuffled π Men gave 78).
- Primary endpoint: global two-sample **event-rate** test, targets vs matched controls,
  negative-binomial rate model (Poisson only as a sensitivity check).
- Benjamini–Hochberg FDR across stars and windows; **look-elsewhere** trials factor
  includes every pre-registered parameter grid. `α_global = 0.01`.
- Report 95% bootstrap confidence intervals and, when null, **upper limits**.
- No undefined rate ratios against a zero control count.

---

## 7. Decisive falsification tests (pre-registered verdicts)

1. Event rate consistent with matched controls at 95% ⇒ **H1 rejected**.
2. Events vanish under hard mask or 5σ clipping ⇒ **instrumental**.
3. Events coincide with shared CCD-wide systematics / scattered-light epochs ⇒ **instrumental**.
4. No recurrence of the same stars in S70/71 vs S42–44 ⇒ **not persistent**.
5. Estimator lacks dynamic range on simulations ⇒ **method invalid; stop**.
6. Two events do not establish a ~12-day periodicity (≥3 cycles + periodogram FAP required).

Pixel-level vetting for **every** surviving event: TPF/FFI cutout, difference image,
centroid motion, background flux, CROWDSAP, quality flags, momentum-dump times, and the
same timestamps in neighbouring stars on the same CCD.

---

## 8. Validation

≥1000 injections over a grid (depth 0.02–2%, bit length 0.5–4 h, duty cycle 0.1–0.5),
reporting **completeness and false-alarm-rate ROC curves**, benchmarked against a matched
filter / BLS on identical data. Sensitivity does **not** bound the false-positive rate;
they are reported separately. The original claim that injections "rule out sub-threshold
instrumental noise" is withdrawn.

---

## 9. Reproducibility

One entry point (`pipeline/run_study_v2.py`, to be implemented) regenerates every table
and figure from MAST product IDs. Pinned lockfile, fixed seeds (surrogates 20261114,
injections 20261115, bootstrap 20261116), archived FITS/product IDs, Zenodo DOI for the
exact snapshot. Figures must fail on missing inputs.

---

## 10. Scope and authorship

- **Sole human author:** A. R. Lingle, independent researcher, working email.
  AI assistance is disclosed in acknowledgements; an AI tool is **not** an author.
- `darpa-classified-summary.md` and `reports/observational-network-switch-report.md`
  are **excluded** from the scientific package (removal is the next work item).
  Ground-based stellar flicker in video is atmospheric scintillation and is not evidence.
- Node labels (`sender_node`, `switch_node`) are replaced by neutral identifiers.
- Prior work to engage: Arnold 2005; Wright et al. 2016; Boyajian et al. 2016;
  Giles & Walkowicz 2019; Wheeler & Kipping 2019; Wright, Kanodia & Lubar 2018;
  Sheikh 2020; Lempel & Ziv 1976; Bandt & Pompe 2002; Rosso et al. 2007.
  Mission/pipeline citations: Ricker et al. 2015; Jenkins et al. 2016; Huang et al. 2020.

---

## 11. Honest prior

The referee's Section 6 states that a careful version of steps 1–4 would **most likely
find event rates consistent with controls**. I share that expectation. If so, the correct,
publishable output is a calibrated null result that constrains the hypothesis — not a
rescued detection. That is the point of pre-registering this document.

---

**Protocol SHA-256:** *computed by `build_sample_v2.py --self-test` and embedded in every
output catalog.* Editing `config/protocol.json` changes the hash and invalidates all
downstream artifacts.
