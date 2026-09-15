"""Display-only RGB composite with one fixed stretch for every date (T4)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import rasterio

from oceanos.domain import TrueColourSpec


def stretch_to_byte(reflectance: np.ndarray, spec: TrueColourSpec) -> np.ndarray:
    """Map reflectance to 1..255 with the fixed stretch and gamma; non-finite pixels become 0 (nodata)."""
    low, high = spec.stretch
    finite = np.isfinite(reflectance)
    scaled = np.clip((np.where(finite, reflectance, low) - low) / (high - low), 0.0, 1.0) ** (1.0 / spec.gamma)
    byte = (1 + np.round(scaled * 254)).astype("uint8")
    byte[~finite] = 0
    return byte


def write_true_colour(sources: tuple[Path, Path, Path], destination: Path, spec: TrueColourSpec) -> None:
    """Combine three aligned single-band reflectance GeoTIFFs (R, G, B) into a 3-band uint8 GeoTIFF."""
    bands = []
    profile = None
    for source in sources:
        with rasterio.open(source) as dataset:
            if profile is None:
                profile = dataset.profile
            elif (dataset.crs, dataset.transform, dataset.width, dataset.height) != (
                profile["crs"], profile["transform"], profile["width"], profile["height"],
            ):
                raise ValueError("true-colour bands must share one grid")
            bands.append(stretch_to_byte(dataset.read(1), spec))
    assert profile is not None
    profile.update(count=3, dtype="uint8", nodata=0, photometric="RGB", predictor=2)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}-", suffix=".tif", delete=False) as stream:
            temporary = Path(stream.name)
        with rasterio.open(temporary, "w", **profile) as written:
            written.write(np.stack(bands))
            written.update_tags(display_only="true", stretch=repr(spec.stretch), gamma=repr(spec.gamma))
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
