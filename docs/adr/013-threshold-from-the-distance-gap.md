# ADR-013: Cut the threshold at the distance gap, not at a quantile

## Status

Accepted — 2026-08-28

## Context

`compute_suggested_threshold` proposed a corridor threshold from robust
quantiles: `Q3 + k·IQR`, relaxed towards P90 when the strict bound would
discard more than ~10 % of the sample. `k` was configurable
(`iqr_multiplier`), and the operator's `config.json` had it edited to **3.0**
— evidence in itself that the default of 1.5 was not producing the right
answer.

Measured on two real deliveries, the distance distribution is not a continuum
at all. It is two populations: the photos on the trace, and a handful taken
somewhere else entirely (take-off, another site).

| Job | p75 | p90 | p95 | max | the jump |
|---|---|---|---|---|---|
| Torre Pacheco, 117 photos | 4.4 m | 7.5 m | 76.3 m | 420 m | 10.8 → 44.6 m (×4) |
| Lorca-Pulpí, 238 photos | 9.7 m | 19.7 m | 670.3 m | 1496 m | 23.9 → 112 m (×5) |

Between the two groups the count barely moves: on Torre Pacheco every
threshold from 15 m to 100 m keeps the same photos. The boundary is the jump,
and no quantile of a bimodal sample lands on it reliably — which is exactly
why `k` had to be tuned by hand, and why with the default the two jobs lost 1
and 4 corridor photos respectively.

## Decision

`find_distance_gap` scans the upper half of the sorted distances for the
largest **relative** jump and returns it when it is dominant: at least ×3, with
at least half the sample below it, ignoring jumps under 1 m (GNSS jitter) and
samples of fewer than 8 photos. When there is such a gap,
`compute_suggested_threshold` cuts there (`method: "gap"`); otherwise the
quantile branches run exactly as before.

The threshold sits a few metres past the last corridor photo —
`low + max(10 % of low, 3 m)`, never reaching the first outlier. Flush against
the last photo would drop it next month over a couple of metres of GNSS
scatter; halfway across the jump would sit in empty space and let a genuinely
off-corridor photo in.

The evidence (`gap_low`, `gap_high`, `gap_ratio`, `gap_inside`) travels with
the result, so the dialog can state *why*: "salto de 23.9 m a 112 m (×5); 219
fotos por debajo; cualquier umbral dentro del salto da el mismo resultado".

## Consequences

- On both real jobs the multiplier stops mattering: `k=1.5` and `k=3.0` now
  produce the same threshold and the same photo set (13.8 m → 110/117 and
  26.9 m → 219/238). The operator does not have to tune anything per corridor.
- The chosen number is lower than the tuned quantile answer while keeping the
  same photos, which is easier to defend in a delivery.
- Continuous distributions are untouched: no dominant gap, so the quantile
  branches run and produce exactly the values they did before.
- Trade-off: a bimodal sample where the far group is a *legitimate* second
  pass gets cut too. Both the old relaxed branch and the new rule excluded it
  in the case covered by the tests, so this is not a regression — but it is
  the failure mode to watch, and the reason the gap evidence is surfaced
  instead of just a number.
- `iqr_multiplier` stays in the config as the fallback knob. It now only bites
  on jobs with no clear gap.
