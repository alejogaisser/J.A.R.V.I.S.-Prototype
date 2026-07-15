"""Local symbolic/numeric mathematics and exportable 2D/3D plots."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from utils.temp_files import temporary_output

_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
_FORBIDDEN = re.compile(r"(__|[\[\]{};'\"`]|\b(import|lambda|exec|eval|open)\b)")
_SYMBOL_NAMES = ("x", "y", "z", "t", "u", "v", "a", "b", "c", "n")
_FUNCTION_NAMES = {
    "sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh",
    "exp", "log", "sqrt", "Abs", "floor", "ceiling", "factorial", "gamma",
    "pi", "E", "oo",
}


def _sympy():
    try:
        import sympy as sp
    except ImportError as exc:
        raise RuntimeError("SymPy is not installed. Install requirements.txt first.") from exc
    return sp


def _parse(raw: str):
    sp = _sympy()
    text = str(raw).strip().replace("^", "**")
    if not text or _FORBIDDEN.search(text):
        raise ValueError("Unsafe or empty mathematical expression")
    allowed = set(_SYMBOL_NAMES) | _FUNCTION_NAMES
    unknown = {token for token in _IDENTIFIER.findall(text) if token not in allowed}
    if unknown:
        raise ValueError(f"Unsupported identifiers: {', '.join(sorted(unknown))}")
    locals_map = {name: sp.Symbol(name, real=True) for name in _SYMBOL_NAMES}
    locals_map.update({name: getattr(sp, name) for name in _FUNCTION_NAMES})
    return sp.sympify(text, locals=locals_map), locals_map


def _matrix(raw):
    sp = _sympy()
    values = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(values, list) or not values or not all(isinstance(row, list) for row in values):
        raise ValueError("matrix must be a non-empty JSON array of rows")
    return sp.Matrix([[_parse(str(value))[0] for value in row] for row in values])


def _gauss_steps(matrix) -> tuple[list[str], object]:
    m = matrix.copy()
    steps, pivot_row = [], 0
    for col in range(m.cols):
        pivot = next((row for row in range(pivot_row, m.rows) if m[row, col] != 0), None)
        if pivot is None:
            continue
        if pivot != pivot_row:
            m.row_swap(pivot, pivot_row)
            steps.append(f"R{pivot_row + 1} ↔ R{pivot + 1}: {m.tolist()}")
        pivot_value = m[pivot_row, col]
        if pivot_value != 1:
            m.row_op(pivot_row, lambda value, _: value / pivot_value)
            steps.append(f"R{pivot_row + 1} ← R{pivot_row + 1}/{pivot_value}: {m.tolist()}")
        for row in range(m.rows):
            factor = m[row, col]
            if row != pivot_row and factor != 0:
                m.row_op(row, lambda value, j: value - factor * m[pivot_row, j])
                steps.append(f"R{row + 1} ← R{row + 1} - ({factor})R{pivot_row + 1}: {m.tolist()}")
        pivot_row += 1
        if pivot_row == m.rows:
            break
    return steps, m


def _plot(args: dict, is_3d: bool) -> str:
    try:
        os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "jarvis-matplotlib"))
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Matplotlib and NumPy are required for plots.") from exc
    sp = _sympy()
    expr, symbols = _parse(args["expression"])
    requested = str(args.get("output_path") or "").strip()
    output = (
        Path(requested).expanduser().resolve()
        if requested else temporary_output(prefix="grafico-3d" if is_3d else "grafico-2d")
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    low, high = float(args.get("min", -10)), float(args.get("max", 10))
    fig = plt.figure(figsize=(9, 6))
    if is_3d:
        x_values = np.linspace(low, high, 160)
        y_values = np.linspace(low, high, 160)
        xx, yy = np.meshgrid(x_values, y_values)
        fn = sp.lambdify((symbols["x"], symbols["y"]), expr, "numpy")
        zz = np.asarray(fn(xx, yy), dtype=float)
        ax = fig.add_subplot(111, projection="3d")
        ax.plot_surface(xx, yy, zz, cmap="viridis", linewidth=0)
        ax.set(xlabel="x", ylabel="y", zlabel=str(expr))
    else:
        x_values = np.linspace(low, high, 1200)
        fn = sp.lambdify(symbols["x"], expr, "numpy")
        y_values = np.asarray(fn(x_values), dtype=float)
        if y_values.ndim == 0:
            y_values = np.full_like(x_values, y_values)
        y_values[~np.isfinite(y_values)] = np.nan
        ax = fig.add_subplot(111)
        ax.plot(x_values, y_values, label=str(expr))
        roots = [root for root in sp.solve(expr, symbols["x"]) if root.is_real and low <= float(root) <= high]
        if roots:
            ax.scatter([float(root) for root in roots], [0] * len(roots), color="red", label="roots")
        derivative = sp.diff(expr, symbols["x"])
        extrema = [root for root in sp.solve(derivative, symbols["x"]) if root.is_real and low <= float(root) <= high]
        if extrema:
            ex = [float(root) for root in extrema]
            ey = [float(expr.subs(symbols["x"], root)) for root in extrema]
            ax.scatter(ex, ey, color="orange", label="stationary points")
        ax.axhline(0, color="black", linewidth=.6)
        ax.axvline(0, color="black", linewidth=.6)
        ax.grid(True, alpha=.25)
        ax.legend()
    fig.tight_layout()
    fig.savefig(output, dpi=160)
    plt.close(fig)
    return f"Plot ready at {output}" + ("" if requested else " (temporary; cleaned automatically after 7 days)")


def math_engine(parameters: dict, player=None) -> str:
    sp = _sympy()
    args = dict(parameters or {})
    action = str(args.get("action", "simplify")).lower().strip()
    try:
        if action in {"plot2d", "plot3d"}:
            return _plot(args, action == "plot3d")
        if action in {"matrix", "gauss"}:
            matrix = _matrix(args.get("matrix"))
            if action == "gauss":
                steps, reduced = _gauss_steps(matrix)
                return "Gaussian elimination:\n" + "\n".join(steps or ["Already reduced."]) + f"\nRREF: {reduced.tolist()}"
            operation = str(args.get("matrix_operation", "determinant")).lower()
            results = {
                "determinant": lambda: matrix.det(), "inverse": lambda: matrix.inv(),
                "rank": lambda: matrix.rank(), "eigenvalues": lambda: matrix.eigenvals(),
                "eigenvectors": lambda: matrix.eigenvects(), "transpose": lambda: matrix.T,
                "rref": lambda: matrix.rref(),
            }
            if operation not in results:
                raise ValueError(f"Unknown matrix operation: {operation}")
            return f"Exact {operation}: {results[operation]()}"
        expr, symbols = _parse(args.get("expression", ""))
        variable = symbols.get(str(args.get("variable", "x")))
        if variable is None:
            raise ValueError("variable must be one of x, y, z, t, u, v, a, b, c, n")
        if action == "simplify":
            result = sp.simplify(expr)
        elif action == "solve":
            rhs, _ = _parse(args.get("rhs", "0"))
            result = sp.solve(sp.Eq(expr, rhs), variable)
        elif action == "derivative":
            result = sp.diff(expr, variable, int(args.get("order", 1)))
        elif action == "integral":
            if "lower" in args and "upper" in args:
                lower, _ = _parse(str(args["lower"])); upper, _ = _parse(str(args["upper"]))
                result = sp.integrate(expr, (variable, lower, upper))
            else:
                result = sp.integrate(expr, variable)
        elif action == "limit":
            point, _ = _parse(str(args.get("point", "0")))
            result = sp.limit(expr, variable, point, dir=str(args.get("direction", "+-")))
        elif action == "numeric":
            result = sp.N(expr, int(args.get("precision", 12)))
        else:
            raise ValueError(f"Unknown math action: {action}")
        return f"Exact result: {result}" if action != "numeric" else f"Numeric approximation: {result}"
    except Exception as exc:
        return f"Math error: {exc}"
