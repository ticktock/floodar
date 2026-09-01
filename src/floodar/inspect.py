"""Summary statistics and histograms for elevation arrays."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Stats:
    count: int              # valid (unmasked) cells
    nodata_count: int       # masked cells
    min: float
    max: float
    mean: float
    std: float
    percentiles: dict[float, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = {
            "count": self.count,
            "nodata_count": self.nodata_count,
            "min": self.min,
            "max": self.max,
            "mean": self.mean,
            "std": self.std,
        }
        d.update({f"p{int(k)}": v for k, v in self.percentiles.items()})
        return d


def stats(arr, percentiles: tuple[float, ...] = (1, 5, 25, 50, 75, 95, 99)) -> Stats:
    """Compute summary statistics over the valid cells of a (masked) array."""
    ma = np.ma.masked_invalid(arr)
    valid = ma.compressed()
    nodata_count = int(ma.size - valid.size)
    if valid.size == 0:
        return Stats(0, nodata_count, float("nan"), float("nan"),
                     float("nan"), float("nan"), {p: float("nan") for p in percentiles})
    pct = np.percentile(valid, percentiles)
    return Stats(
        count=int(valid.size),
        nodata_count=nodata_count,
        min=float(valid.min()),
        max=float(valid.max()),
        mean=float(valid.mean()),
        std=float(valid.std()),
        percentiles={float(p): float(v) for p, v in zip(percentiles, pct)},
    )


def histogram(arr, bins: int = 50, value_range: tuple[float, float] | None = None):
    """Return (counts, bin_edges) over valid cells — useful for spotting nodata
    sentinels, water surfaces (flat spikes), and the overall elevation spread."""
    valid = np.ma.masked_invalid(arr).compressed()
    if valid.size == 0:
        return np.array([]), np.array([])
    return np.histogram(valid, bins=bins, range=value_range)
