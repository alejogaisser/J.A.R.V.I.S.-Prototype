from __future__ import annotations

import math
import pytest
from unittest.mock import patch
from pathlib import Path

from actions.study_engine import provider_status, study_engine


class _Player:
    def __init__(self):
        self.calls = []

    def show_study_result(self, artifact, automatic=True):
        self.calls.append((artifact, automatic))
        return "Study result stored."


def test_plot2d_creates_interactive_artifact_and_displays_it():
    player = _Player()
    result = study_engine(
        {"action": "plot2d", "expression": "x^2-4", "min": -3, "max": 3},
        player=player,
    )
    assert result["success"] is True
    artifact, automatic = player.calls[0]
    assert automatic is True
    assert artifact["visualization"]["type"] == "plot2d"
    assert len(artifact["visualization"]["x"]) == 801
    assert artifact["visualization"]["y"][0] == 5.0


def test_plot3d_samples_a_real_surface():
    result = study_engine({"action": "plot3d", "expression": "x^2+y^2", "min": -2, "max": 2})
    visual = result["artifact"]["visualization"]
    assert result["success"] is True
    assert visual["type"] == "plot3d"
    assert len(visual["z"]) == 51
    assert len(visual["z"][0]) == 51


def test_free_body_diagram_has_verified_vector_result():
    result = study_engine({
        "action": "free_body",
        "forces": [
            {"label": "Right", "magnitude": 10, "angle_deg": 0},
            {"label": "Up", "magnitude": 10, "angle_deg": 90},
        ],
    })
    artifact = result["artifact"]
    assert result["success"] is True
    assert artifact["visualization"]["type"] == "free_body"
    assert "14.1421" in artifact["result"]
    assert math.isclose(artifact["visualization"]["sum_x"], 10.0)


def test_present_keeps_model_reasoning_structured():
    result = study_engine({
        "action": "present", "subject": "physics", "title": "Energy",
        "problem": "Find kinetic energy", "result": "20 J", "steps": ["Use K=mv^2/2"],
    })
    assert result["success"] is True
    assert result["artifact"]["subject"] == "PHYSICS"
    assert result["artifact"]["steps"] == ["Use K=mv^2/2"]


def test_wolfram_is_optional_and_reports_missing_app_id(monkeypatch):
    monkeypatch.delenv("WOLFRAM_ALPHA_APP_ID", raising=False)
    result = study_engine({"action": "wolfram", "query": "2+2"})
    assert result["success"] is False
    assert "WOLFRAM_ALPHA_APP_ID" in result["error"]
    assert provider_status()["wolfram"]["available"] is False


def test_geogebra_artifact_is_explicitly_optional():
    result = study_engine({"action": "geogebra", "expression": "f(x)=sin(x)"})
    assert result["success"] is True
    assert result["artifact"]["visualization"] == {
        "type": "geogebra", "expression": "f(x)=sin(x)"
    }


def test_rdkit_renders_local_smiles_without_network():
    if not provider_status()["chemistry_local"]["available"]:
        pytest.skip("RDKit is an optional runtime dependency in this test environment")
    result = study_engine({"action": "molecule", "query": "ethanol", "smiles": "CCO"})
    assert result["success"] is True
    visual = result["artifact"]["visualization"]
    assert visual["type"] == "molecule"
    assert visual["smiles"] == "CCO"
    assert "<svg" in visual["svg"]
    assert "3D" in visual["molblock"]


def test_anatomy_builds_interactive_educational_3d_schematic():
    result = study_engine({"action": "anatomy", "organ": "corazón"})
    assert result["success"] is True
    artifact = result["artifact"]
    assert artifact["subject"] == "ANATOMY"
    assert artifact["visualization"]["type"] == "anatomy"
    assert artifact["visualization"]["organ"] == "heart"
    assert len(artifact["visualization"]["parts"]) >= 4
    assert any("diagnosis" in note for note in artifact["notes"])


def test_unknown_anatomy_model_fails_instead_of_inventing_one():
    result = study_engine({"action": "anatomy", "organ": "órgano imaginario"})
    assert result["success"] is False
    assert "unsupported anatomy model" in result["error"]


def test_smiles_uses_pubchem_3d_fallback_without_local_rdkit():
    remote = {
        "Title": "Ethanol", "MolecularFormula": "C2H6O",
        "MolecularWeight": "46.07", "IsomericSMILES": "CCO",
        "molblock": "Ethanol\n  PubChem3D\n\n  0  0  0  0  0  0  0  0  0  0999 V3000\n",
    }
    with (
        patch("actions.study_engine._rdkit_3d_molblock", return_value=""),
        patch("actions.study_engine._pubchem_record", return_value=remote) as pubchem,
    ):
        result = study_engine({"action": "molecule", "smiles": "CCO"})
    assert result["success"] is True
    assert result["artifact"]["visualization"]["dimension"] == "3d"
    assert result["artifact"]["visualization"]["molblock"] == remote["molblock"]
    pubchem.assert_called_once_with("CCO", namespace="smiles")


def test_study_plots_and_anatomy_have_dependency_free_local_renderers():
    source = Path("ui_mk2/study.py").read_text(encoding="utf-8")
    assert "cdn.plot.ly" not in source
    assert "INTERACTIVE PLOT ENGINE OFFLINE" not in source
    assert "INTERACTIVE ANATOMY ENGINE OFFLINE" not in source
    assert "function renderPlot2dLocal" in source
    assert "function renderPlot3dLocal" in source
    assert "function renderAnatomyLocal" in source
    assert "DRAG TO ROTATE  ·  WHEEL TO ZOOM  ·  LOCAL RENDERER" in source


def test_unsafe_math_is_rejected_without_fake_success():
    result = study_engine({"action": "plot2d", "expression": "__import__('os')"})
    assert result["success"] is False
    assert result["error"].startswith("Study error:")
