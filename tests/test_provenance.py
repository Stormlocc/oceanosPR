"""ProvenanceRecord is complete and self-contained for a published release (contracts §5)."""

from __future__ import annotations

import json
import socket
from hashlib import sha256
from pathlib import Path

import pytest
from support.pipeline_env import OVERPASS, make_env

from oceanos.domain import ProvenanceRecord
from oceanos.pipeline.run_one import run_one


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Provenance tests must not access the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def test_provenance_has_required_sections_and_lineage(tmp_path: Path, monkeypatch) -> None:
    env = make_env(tmp_path, monkeypatch)
    result = run_one(env.settings, OVERPASS, **env.configs(), dependencies=env.dependencies())
    raw = json.loads((result.release_dir / "provenance.json").read_text(encoding="utf-8"))

    assert {"scenes", "acolite", "oceanos", "ancillary", "products", "scientific_label"} <= raw.keys()
    record = ProvenanceRecord.model_validate(raw)
    assert record.scientific_label and "not validated" in record.scientific_label
    assert record.oceanos.quality_policy_version == env.policy.version
    assert record.oceanos.publication_profile_id == env.publication.profile_id
    assert record.glint_angle_deg == pytest.approx(22.13106635390421)
    assert any("glint_angle_deg" in item for item in record.derivations)

    products = {product.product_key: product for product in record.products}
    assert set(products) == {"tur_nechad2016", "spm_nechad2016", "chl_re_gons740", "fai", "fait", "ndvi", "l2_flags", "true_colour"}
    assert products["tur_nechad2016"].shallow_exclusion_m == 7 and products["fai"].shallow_exclusion_m is None
    assert products["chl_re_gons740"].caveat and "NOT reliable" in products["chl_re_gons740"].caveat
    assert products["true_colour"].acolite_variable == ("rhos_665", "rhos_560", "rhos_492")
    assert products["fai"].land_mask is None and products["tur_nechad2016"].land_mask is not None

    mask_json = env.layout.grid_json(env.aoi_id).parent / "analysis_mask.json"
    assert record.analysis_mask is not None
    assert record.analysis_mask.sha256 == sha256(mask_json.read_bytes()).hexdigest()
    assert str(env.root) not in (result.release_dir / "provenance.json").read_text(encoding="utf-8")
