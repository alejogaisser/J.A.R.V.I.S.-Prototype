"""Structured, verifiable Study artifacts with optional scientific providers."""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import quote

import requests

from actions.math_engine import _matrix, _parse, _sympy, math_engine


@dataclass
class StudyArtifact:
    subject: str
    title: str
    problem: str = ""
    result: str = ""
    steps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    visualization: dict[str, Any] = field(default_factory=dict)
    sources: list[dict[str, str]] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def provider_status() -> dict[str, dict[str, Any]]:
    try:
        import rdkit  # noqa: F401
        rdkit_ready = True
    except ImportError:
        rdkit_ready = False
    return {
        "local_math": {"available": True, "provider": "SymPy"},
        "physics": {"available": True, "provider": "JARVIS vector engine"},
        "chemistry_local": {"available": rdkit_ready, "provider": "RDKit"},
        "pubchem": {"available": True, "provider": "NCBI PubChem", "limit": "5 requests/second"},
        "anatomy": {
            "available": True,
            "provider": "JARVIS procedural anatomy",
            "mode": "interactive educational schematic",
        },
        "geogebra": {"available": True, "provider": "GeoGebra", "mode": "optional non-commercial embed"},
        "wolfram": {
            "available": bool(os.getenv("WOLFRAM_ALPHA_APP_ID", "").strip()),
            "provider": "Wolfram|Alpha",
            "requires": "WOLFRAM_ALPHA_APP_ID",
        },
    }


def _sample_plot(expression: str, is_3d: bool, low: float, high: float) -> dict[str, Any]:
    import numpy as np

    expr, symbols = _parse(expression)
    if not math.isfinite(low) or not math.isfinite(high) or low >= high or high - low > 10000:
        raise ValueError("plot range must be finite, increasing, and no wider than 10000")
    if is_3d:
        axis = np.linspace(low, high, 51)
        xx, yy = np.meshgrid(axis, axis)
        values = np.asarray(
            _sympy().lambdify((symbols["x"], symbols["y"]), expr, "numpy")(xx, yy),
            dtype=float,
        )
        if values.ndim == 0:
            values = np.full_like(xx, values)
        values[~np.isfinite(values)] = np.nan
        return {
            "type": "plot3d", "expression": str(expr),
            "x": axis.round(7).tolist(), "y": axis.round(7).tolist(),
            "z": [[None if not math.isfinite(v) else round(float(v), 7) for v in row] for row in values],
        }
    axis = np.linspace(low, high, 801)
    values = np.asarray(_sympy().lambdify(symbols["x"], expr, "numpy")(axis), dtype=float)
    if values.ndim == 0:
        values = np.full_like(axis, values)
    values[~np.isfinite(values)] = np.nan
    return {
        "type": "plot2d", "expression": str(expr),
        "x": axis.round(7).tolist(),
        "y": [None if not math.isfinite(v) else round(float(v), 7) for v in values],
    }


def _math_artifact(args: dict[str, Any], action: str) -> StudyArtifact:
    result = math_engine({**args, "action": action})
    if result.startswith("Math error:"):
        raise ValueError(result.removeprefix("Math error: "))
    problem = str(args.get("expression") or args.get("matrix") or "")
    visualization: dict[str, Any] = {}
    if action in {"plot2d", "plot3d"}:
        visualization = _sample_plot(
            str(args["expression"]), action == "plot3d",
            float(args.get("min", -10)), float(args.get("max", 10)),
        )
        result = f"Interactive {'3D surface' if action == 'plot3d' else '2D function'} generated."
    steps = result.splitlines() if action == "gauss" else []
    return StudyArtifact(
        subject="MATHEMATICS", title=action.replace("_", " ").upper(),
        problem=problem, result=result, steps=steps, visualization=visualization,
        notes=["Computed locally with SymPy; exact unless marked numeric."],
    )


def _free_body(args: dict[str, Any]) -> StudyArtifact:
    raw = args.get("forces", [])
    forces = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(forces, list) or not forces:
        raise ValueError("forces must be a non-empty list")
    normalized, sx, sy = [], 0.0, 0.0
    for index, force in enumerate(forces, 1):
        if not isinstance(force, dict):
            raise ValueError("each force must contain label, magnitude and angle_deg")
        magnitude = float(force.get("magnitude", 0))
        angle = float(force.get("angle_deg", 0))
        if not math.isfinite(magnitude) or magnitude < 0 or not math.isfinite(angle):
            raise ValueError("force magnitudes and angles must be finite; magnitude cannot be negative")
        fx = magnitude * math.cos(math.radians(angle)); fy = magnitude * math.sin(math.radians(angle))
        sx += fx; sy += fy
        normalized.append({
            "label": str(force.get("label") or f"F{index}"), "magnitude": magnitude,
            "angle_deg": angle, "fx": round(fx, 6), "fy": round(fy, 6),
        })
    resultant = math.hypot(sx, sy)
    direction = math.degrees(math.atan2(sy, sx)) if resultant else 0.0
    return StudyArtifact(
        subject="PHYSICS", title=str(args.get("title") or "FREE-BODY DIAGRAM"),
        problem=str(args.get("problem") or "Structured force system"),
        result=f"Resultant: {resultant:.6g} N at {direction:.3f}°; ΣFx={sx:.6g} N, ΣFy={sy:.6g} N.",
        steps=[f"{f['label']}: Fx={f['fx']:.6g} N, Fy={f['fy']:.6g} N" for f in normalized],
        visualization={"type": "free_body", "forces": normalized, "sum_x": sx, "sum_y": sy},
        notes=["Angles are measured counter-clockwise from the positive x-axis."],
    )


def _pubchem_record(query: str, namespace: str = "name") -> dict[str, Any]:
    if namespace not in {"name", "smiles"}:
        raise ValueError("unsupported PubChem identifier namespace")
    base = (
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/"
        f"{namespace}/{quote(query, safe='')}"
    )
    props = requests.get(
        base + "/property/Title,MolecularFormula,MolecularWeight,IsomericSMILES/JSON",
        timeout=10,
    )
    props.raise_for_status()
    record = props.json()["PropertyTable"]["Properties"][0]
    sdf = requests.get(base + "/SDF?record_type=3d", timeout=12)
    if sdf.ok:
        record["molblock"] = sdf.text[:250000]
    return record


def _rdkit_3d_molblock(smiles: str) -> str:
    """Build a deterministic local conformer so SMILES are genuinely 3D."""
    if not smiles:
        return ""
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError:
        return ""

    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        return ""
    molecule = Chem.AddHs(molecule)
    parameters = AllChem.ETKDGv3()
    parameters.randomSeed = 0x4A415256  # Stable JARV seed for repeatable diagrams.
    if AllChem.EmbedMolecule(molecule, parameters) != 0:
        return ""
    try:
        if AllChem.MMFFHasAllMoleculeParams(molecule):
            AllChem.MMFFOptimizeMolecule(molecule, maxIters=300)
        else:
            AllChem.UFFOptimizeMolecule(molecule, maxIters=300)
    except (RuntimeError, ValueError):
        # A usable embedded conformer is preferable to silently falling back to 2D.
        pass
    return Chem.MolToMolBlock(molecule)


def _molecule(args: dict[str, Any]) -> StudyArtifact:
    query = str(args.get("query") or args.get("smiles") or "").strip()
    if not query:
        raise ValueError("query or smiles is required")
    record: dict[str, Any] = {"Title": query, "SMILES": str(args.get("smiles") or "")}
    source = "local"
    if not args.get("smiles"):
        record = _pubchem_record(query); source = "PubChem"
    smiles = str(record.get("SMILES") or record.get("IsomericSMILES") or "")
    svg = ""
    try:
        from rdkit import Chem
        from rdkit.Chem.Draw import rdMolDraw2D
        molecule = Chem.MolFromSmiles(smiles) if smiles else None
        if molecule:
            drawer = rdMolDraw2D.MolDraw2DSVG(720, 420)
            options = drawer.drawOptions(); options.bondLineWidth = 2.0
            drawer.DrawMolecule(molecule); drawer.FinishDrawing(); svg = drawer.GetDrawingText()
    except ImportError:
        pass
    title = str(record.get("Title") or query)
    formula = str(record.get("MolecularFormula") or "unknown")
    weight = str(record.get("MolecularWeight") or "unknown")
    molblock = str(record.get("molblock") or "")
    if not molblock:
        molblock = _rdkit_3d_molblock(smiles)
    if not molblock and smiles:
        # Minimal installations may not have RDKit yet. PubChem can still
        # supply a reference 3D conformer for an explicit SMILES.
        try:
            remote = _pubchem_record(smiles, namespace="smiles")
            molblock = str(remote.get("molblock") or "")
            for field in ("Title", "MolecularFormula", "MolecularWeight"):
                if remote.get(field):
                    record[field] = remote[field]
            source = "PubChem"
            title = str(record.get("Title") or title)
            formula = str(record.get("MolecularFormula") or formula)
            weight = str(record.get("MolecularWeight") or weight)
        except requests.RequestException:
            pass
    if not molblock:
        raise RuntimeError(
            "3D coordinates are unavailable; install RDKit or connect to PubChem and retry"
        )
    return StudyArtifact(
        subject="CHEMISTRY", title=title.upper(), problem=query,
        result=f"Formula: {formula}; molecular weight: {weight} g/mol.",
        visualization={
            "type": "molecule", "smiles": smiles, "svg": svg,
            "molblock": molblock, "dimension": "3d",
        },
        sources=[{"name": source, "url": "https://pubchem.ncbi.nlm.nih.gov/"}] if source == "PubChem" else [],
        notes=["3D coordinates are reference conformers, not a full conformational analysis."],
    )


_ANATOMY_ALIASES = {
    "heart": "heart", "corazon": "heart", "corazón": "heart",
    "lungs": "lungs", "lung": "lungs", "pulmon": "lungs", "pulmón": "lungs",
    "pulmones": "lungs",
    "brain": "brain", "cerebro": "brain", "encefalo": "brain", "encéfalo": "brain",
    "liver": "liver", "higado": "liver", "hígado": "liver",
    "kidney": "kidney", "riñon": "kidney", "riñón": "kidney",
    "kidneys": "kidneys", "riñones": "kidneys",
    "stomach": "stomach", "estomago": "stomach", "estómago": "stomach",
    "eye": "eye", "ojo": "eye",
}

_ANATOMY_MODELS: dict[str, dict[str, Any]] = {
    "heart": {
        "title": "HEART / CORAZÓN",
        "result": "Interactive 3D schematic of the cardiac chambers and great vessels.",
        "parts": [
            {"shape": "ellipsoid", "center": [-0.42, 0.10, 0], "scale": [0.72, 1.02, 0.66], "color": "#ff506f", "label": "right heart"},
            {"shape": "ellipsoid", "center": [0.38, 0.02, 0], "scale": [0.68, 1.12, 0.72], "color": "#d91f4d", "label": "left heart"},
            {"shape": "tube", "center": [0.20, 1.12, 0], "scale": [0.22, 0.86, 0.22], "color": "#ff3158", "label": "aorta"},
            {"shape": "tube", "center": [-0.43, 1.00, 0.08], "scale": [0.18, 0.66, 0.18], "color": "#42bfff", "label": "vena cava"},
        ],
    },
    "lungs": {
        "title": "LUNGS / PULMONES",
        "result": "Interactive 3D schematic of both lungs, trachea, and main bronchi.",
        "parts": [
            {"shape": "ellipsoid", "center": [-0.62, -0.05, 0], "scale": [0.62, 1.35, 0.58], "color": "#69d9ee", "label": "right lung"},
            {"shape": "ellipsoid", "center": [0.62, -0.05, 0], "scale": [0.58, 1.28, 0.55], "color": "#56bcd5", "label": "left lung"},
            {"shape": "tube", "center": [0, 1.24, 0], "scale": [0.15, 0.85, 0.15], "color": "#d7f8ff", "label": "trachea"},
            {"shape": "tube", "center": [-0.27, 0.66, 0], "scale": [0.10, 0.62, 0.10], "rotation": [0, 0, -0.65], "color": "#bdefff", "label": "right bronchus"},
            {"shape": "tube", "center": [0.27, 0.66, 0], "scale": [0.10, 0.62, 0.10], "rotation": [0, 0, 0.65], "color": "#bdefff", "label": "left bronchus"},
        ],
    },
    "brain": {
        "title": "BRAIN / CEREBRO",
        "result": "Interactive 3D schematic of the cerebral hemispheres, cerebellum, and brainstem.",
        "parts": [
            {"shape": "ellipsoid", "center": [-0.42, 0.20, 0], "scale": [0.86, 0.82, 0.76], "color": "#d882ff", "label": "right hemisphere"},
            {"shape": "ellipsoid", "center": [0.42, 0.20, 0], "scale": [0.86, 0.82, 0.76], "color": "#c15cf2", "label": "left hemisphere"},
            {"shape": "ellipsoid", "center": [0, -0.62, -0.18], "scale": [0.64, 0.42, 0.52], "color": "#9d4ccc", "label": "cerebellum"},
            {"shape": "tube", "center": [0, -0.92, 0], "scale": [0.18, 0.65, 0.18], "color": "#f0bdff", "label": "brainstem"},
        ],
    },
    "liver": {
        "title": "LIVER / HÍGADO",
        "result": "Interactive 3D schematic of the main hepatic lobes and gallbladder.",
        "parts": [
            {"shape": "ellipsoid", "center": [-0.18, 0, 0], "scale": [1.45, 0.72, 0.72], "color": "#a83f45", "label": "right lobe"},
            {"shape": "ellipsoid", "center": [0.82, 0.05, 0.04], "scale": [0.72, 0.55, 0.56], "color": "#c65755", "label": "left lobe"},
            {"shape": "ellipsoid", "center": [0.25, -0.58, 0.45], "scale": [0.18, 0.42, 0.18], "color": "#63c96b", "label": "gallbladder"},
        ],
    },
    "kidney": {
        "title": "KIDNEY / RIÑÓN",
        "result": "Interactive 3D schematic of a kidney and renal pelvis.",
        "parts": [
            {"shape": "ellipsoid", "center": [0, 0, 0], "scale": [0.74, 1.18, 0.58], "color": "#b54a58", "label": "renal cortex"},
            {"shape": "ellipsoid", "center": [0.36, 0, 0.28], "scale": [0.28, 0.58, 0.25], "color": "#f1a76e", "label": "renal pelvis"},
            {"shape": "tube", "center": [0.38, -0.86, 0.28], "scale": [0.10, 0.75, 0.10], "color": "#f4cf82", "label": "ureter"},
        ],
    },
    "kidneys": {
        "title": "KIDNEYS / RIÑONES",
        "result": "Interactive 3D schematic of both kidneys and ureters.",
        "parts": [
            {"shape": "ellipsoid", "center": [-0.72, 0.18, 0], "scale": [0.55, 0.95, 0.48], "color": "#b54a58", "label": "right kidney"},
            {"shape": "ellipsoid", "center": [0.72, 0.18, 0], "scale": [0.55, 0.95, 0.48], "color": "#b54a58", "label": "left kidney"},
            {"shape": "tube", "center": [-0.72, -0.92, 0], "scale": [0.08, 1.20, 0.08], "color": "#f4cf82", "label": "right ureter"},
            {"shape": "tube", "center": [0.72, -0.92, 0], "scale": [0.08, 1.20, 0.08], "color": "#f4cf82", "label": "left ureter"},
        ],
    },
    "stomach": {
        "title": "STOMACH / ESTÓMAGO",
        "result": "Interactive 3D schematic of the stomach, esophagus, and duodenal outlet.",
        "parts": [
            {"shape": "ellipsoid", "center": [0, -0.10, 0], "scale": [0.82, 1.12, 0.65], "rotation": [0, 0, -0.35], "color": "#e98e9e", "label": "stomach"},
            {"shape": "tube", "center": [-0.36, 1.05, 0], "scale": [0.13, 0.82, 0.13], "rotation": [0, 0, -0.15], "color": "#ffc2c9", "label": "esophagus"},
            {"shape": "tube", "center": [0.70, -0.75, 0], "scale": [0.12, 0.72, 0.12], "rotation": [0, 0, 0.85], "color": "#f6b3ba", "label": "duodenum"},
        ],
    },
    "eye": {
        "title": "EYE / OJO",
        "result": "Interactive 3D cutaway schematic of the globe, lens, iris, and optic nerve.",
        "parts": [
            {"shape": "ellipsoid", "center": [0, 0, 0], "scale": [1, 1, 1], "color": "#d9f7ff", "opacity": 0.45, "label": "globe"},
            {"shape": "ellipsoid", "center": [0, 0, 0.72], "scale": [0.55, 0.55, 0.16], "color": "#36b7cb", "label": "iris"},
            {"shape": "ellipsoid", "center": [0, 0, 0.48], "scale": [0.42, 0.42, 0.22], "color": "#fff3b0", "opacity": 0.75, "label": "lens"},
            {"shape": "tube", "center": [0, 0, -1.18], "scale": [0.16, 0.72, 0.16], "rotation": [1.57, 0, 0], "color": "#ffd36a", "label": "optic nerve"},
        ],
    },
}


def _anatomy(args: dict[str, Any]) -> StudyArtifact:
    query = str(args.get("organ") or args.get("query") or "").strip()
    key = _ANATOMY_ALIASES.get(query.casefold())
    if key is None:
        supported = ", ".join(sorted({model["title"].split(" / ")[0].title() for model in _ANATOMY_MODELS.values()}))
        raise ValueError(f"unsupported anatomy model: {query or 'empty query'}. Available: {supported}")
    model = _ANATOMY_MODELS[key]
    return StudyArtifact(
        subject="ANATOMY",
        title=str(model["title"]),
        problem=query,
        result=str(model["result"]),
        visualization={
            "type": "anatomy",
            "organ": key,
            "parts": model["parts"],
        },
        notes=[
            "Educational schematic; proportions and shapes are simplified.",
            "Not intended for diagnosis, surgical planning, or replacement of validated medical atlases.",
        ],
    )


def _wolfram(args: dict[str, Any]) -> StudyArtifact:
    app_id = os.getenv("WOLFRAM_ALPHA_APP_ID", "").strip()
    if not app_id:
        raise RuntimeError("Wolfram adapter is disabled: set WOLFRAM_ALPHA_APP_ID first")
    query = str(args.get("query") or args.get("problem") or "").strip()
    response = requests.get(
        "https://api.wolframalpha.com/v2/query",
        params={"appid": app_id, "input": query, "output": "json", "format": "plaintext"},
        timeout=15,
    )


def _geogebra(args: dict[str, Any]) -> StudyArtifact:
    expression = str(args.get("expression") or args.get("query") or "").strip()
    if not expression:
        raise ValueError("expression is required for GeoGebra")
    # The applet evaluates this command only inside GeoGebra's sandbox. It is
    # intentionally an optional personal/non-commercial visualization path.
    if len(expression) > 500 or any(token in expression.lower() for token in ("javascript", "<script", "http:")):
        raise ValueError("unsupported GeoGebra command")
    return StudyArtifact(
        subject="MATHEMATICS", title="GEOGEBRA INTERACTIVE MODEL", problem=expression,
        result="GeoGebra interactive construction prepared.",
        visualization={"type": "geogebra", "expression": expression},
        sources=[{"name": "GeoGebra", "url": "https://www.geogebra.org/"}],
        notes=["Optional non-commercial educational embed; requires internet access."],
    )
    response.raise_for_status(); data = response.json().get("queryresult", {})
    pods = []
    for pod in data.get("pods", [])[:8]:
        text = "\n".join(s.get("plaintext", "") for s in pod.get("subpods", [])).strip()
        if text: pods.append(f"{pod.get('title', 'Result')}: {text}")
    if not pods:
        raise ValueError("Wolfram returned no interpretable result")
    return StudyArtifact(
        subject="REFERENCE", title="WOLFRAM|ALPHA CHECK", problem=query,
        result=pods[0], steps=pods[1:],
        sources=[{"name": "Wolfram|Alpha", "url": "https://www.wolframalpha.com/"}],
        notes=["External reference result; not cached by JARVIS."],
    )


def _present(args: dict[str, Any]) -> StudyArtifact:
    steps = args.get("steps", [])
    if isinstance(steps, str):
        try: steps = json.loads(steps)
        except json.JSONDecodeError: steps = [line for line in steps.splitlines() if line.strip()]
    return StudyArtifact(
        subject=str(args.get("subject") or "SCIENCE").upper(),
        title=str(args.get("title") or "STUDY BRIEF"),
        problem=str(args.get("problem") or args.get("query") or ""),
        result=str(args.get("result") or ""), steps=[str(step) for step in steps],
        notes=[str(args["note"])] if args.get("note") else [],
    )


def study_engine(parameters: dict, player=None):
    args = dict(parameters or {}); action = str(args.get("action", "status")).lower().strip()
    try:
        if action == "status":
            return {"success": True, "message": "Study providers inspected.", "providers": provider_status()}
        if action == "open":
            if player: return player.show_study_result(None, automatic=False)
            return "Study workspace is available."
        if action in {"simplify", "solve", "derivative", "integral", "limit", "numeric", "matrix", "gauss", "plot2d", "plot3d"}:
            artifact = _math_artifact(args, action)
        elif action == "free_body": artifact = _free_body(args)
        elif action == "molecule": artifact = _molecule(args)
        elif action == "anatomy": artifact = _anatomy(args)
        elif action == "wolfram": artifact = _wolfram(args)
        elif action == "geogebra": artifact = _geogebra(args)
        elif action == "present": artifact = _present(args)
        else: raise ValueError(f"Unknown Study action: {action}")
        display = player.show_study_result(artifact.payload(), automatic=True) if player else "not displayed"
        return {
            "success": True, "message": artifact.result or f"{artifact.title} ready.",
            "artifact": artifact.payload(), "display": display,
        }
    except Exception as exc:
        return {"success": False, "error": f"Study error: {exc}", "message": f"Study error: {exc}"}
