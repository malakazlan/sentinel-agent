"""Distribution comparison utilities — KS test + PSI. Phase 8 / ADR-022.

Pure-numpy implementations so the package has no scipy hard dependency.
When scipy IS installed, ``ks_two_sample`` defers to ``scipy.stats.ks_2samp``
for numerical agreement; the pure-numpy path is the fallback.

Thresholds (cited in the agent prompt + docs):

- PSI < 0.10  →  stable
- PSI 0.10–0.25  →  watch / minor
- PSI > 0.25  →  significant drift
- KS p-value < 0.01  →  statistically significant change

Both report a ``severity`` flag normalized to the 4-tier scale shared
across Phase 8 monitoring agents.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Iterable, Optional


SEVERITY_FLAGS = ("none", "watch", "significant", "severe")


# ── KS two-sample test (pure-numpy fallback) ──────────────────────────────


@dataclass(frozen=True)
class KSResult:
    statistic: float
    p_value: float
    severity: str
    baseline_n: int
    incident_n: int


def ks_two_sample(baseline: list[float], incident: list[float]) -> KSResult:
    """Two-sample Kolmogorov-Smirnov test.

    Uses scipy when available (more accurate p-value); falls back to a
    deterministic pure-Python approximation otherwise. The approximation
    is the standard `1.36/sqrt(n)` cutoff -> p; good enough for the
    severity classification this codebase consumes.
    """
    if not baseline or not incident:
        return KSResult(
            statistic=0.0, p_value=1.0, severity="none",
            baseline_n=len(baseline), incident_n=len(incident),
        )
    try:
        from scipy.stats import ks_2samp  # type: ignore[import-not-found]
        stat, p = ks_2samp(baseline, incident)
        return KSResult(
            statistic=float(stat),
            p_value=float(p),
            severity=_ks_severity(p),
            baseline_n=len(baseline),
            incident_n=len(incident),
        )
    except ImportError:
        pass
    stat = _ks_statistic(baseline, incident)
    p = _ks_p_value(stat, len(baseline), len(incident))
    return KSResult(
        statistic=stat,
        p_value=p,
        severity=_ks_severity(p),
        baseline_n=len(baseline),
        incident_n=len(incident),
    )


def _ks_statistic(a: list[float], b: list[float]) -> float:
    """Two-sample KS statistic = max |F_a(x) - F_b(x)| over combined support."""
    sa = sorted(a)
    sb = sorted(b)
    na, nb = len(sa), len(sb)
    points = sorted(set(sa) | set(sb))
    max_diff = 0.0
    for x in points:
        fa = _ecdf(sa, x, na)
        fb = _ecdf(sb, x, nb)
        max_diff = max(max_diff, abs(fa - fb))
    return max_diff


def _ecdf(sorted_vals: list[float], x: float, n: int) -> float:
    # Binary search bisect_right equivalent (avoid bisect import)
    lo, hi = 0, n
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_vals[mid] <= x:
            lo = mid + 1
        else:
            hi = mid
    return lo / n


def _ks_p_value(stat: float, n1: int, n2: int) -> float:
    """Asymptotic p-value via the Kolmogorov distribution series."""
    en = math.sqrt(n1 * n2 / (n1 + n2))
    lam = (en + 0.12 + 0.11 / en) * stat
    # series sum — converges quickly
    s = 0.0
    fac = 2.0
    for j in range(1, 101):
        term = fac * math.exp(-2 * lam * lam * j * j)
        s += term
        if abs(term) < 1e-10:
            break
        fac = -fac
    return min(1.0, max(0.0, s))


def _ks_severity(p: float) -> str:
    if p < 0.001:
        return "severe"
    if p < 0.01:
        return "significant"
    if p < 0.05:
        return "watch"
    return "none"


# ── Population Stability Index (categorical) ──────────────────────────────


@dataclass(frozen=True)
class PSIResult:
    psi: float
    severity: str
    per_category: dict[str, float]
    baseline_n: int
    incident_n: int


def psi(
    baseline: Iterable[str],
    incident: Iterable[str],
) -> PSIResult:
    """Population Stability Index for two categorical samples.

    PSI = sum over categories of (p_incident - p_baseline) * ln(p_incident / p_baseline)
    with smoothing for empty buckets (epsilon = 1e-4).
    """
    b = list(baseline)
    i = list(incident)
    if not b or not i:
        return PSIResult(
            psi=0.0, severity="none", per_category={},
            baseline_n=len(b), incident_n=len(i),
        )
    cats = sorted(set(b) | set(i))
    eps = 1e-4
    bn = len(b)
    inn = len(i)
    bc = {c: b.count(c) for c in cats}
    ic = {c: i.count(c) for c in cats}
    per_cat: dict[str, float] = {}
    total = 0.0
    for c in cats:
        pb = max(eps, bc[c] / bn)
        pi = max(eps, ic[c] / inn)
        contribution = (pi - pb) * math.log(pi / pb)
        per_cat[c] = contribution
        total += contribution
    return PSIResult(
        psi=total,
        severity=_psi_severity(total),
        per_category=per_cat,
        baseline_n=bn,
        incident_n=inn,
    )


def _psi_severity(value: float) -> str:
    if value < 0.10:
        return "none"
    if value < 0.25:
        return "watch"
    if value < 0.50:
        return "significant"
    return "severe"


# ── Shared summary statistics ─────────────────────────────────────────────


def numeric_summary(values: list[float]) -> dict[str, Optional[float]]:
    if not values:
        return {"n": 0, "mean": None, "stdev": None, "p50": None, "p95": None}
    s = sorted(values)
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "stdev": statistics.pstdev(values) if len(values) > 1 else 0.0,
        "p50": s[len(s) // 2],
        "p95": s[max(0, int(len(s) * 0.95) - 1)],
    }
