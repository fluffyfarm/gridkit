"""Built-in standard line types and Excel import helpers for GridKit.

Pandapower ships standard types for MV/HV lines (``149-AL1/24-ST1A 110.0`` ...).
LV cable types such as ``NAYY 4x50 SE`` are *not* included, so GridKit bundles a
small catalog of common NAYY cables and allows loading custom types from an
Excel workbook (one row per type, one column per parameter).
"""

from __future__ import annotations

from typing import Optional, Sequence

import pandapower as pp

# Parameters from common German cable datasheets (approx., PVC, buried).
# ``c`` is capacitance in nF/km, ``max_i`` in kA.
NAYY_LV_CABLES: dict[str, dict[str, float]] = {
    "NAYY 4x16 SE": dict(r_ohm_per_km=1.91, x_ohm_per_km=0.08, c_nf_per_km=360.0, max_i_ka=0.100),
    "NAYY 4x25 SE": dict(r_ohm_per_km=1.20, x_ohm_per_km=0.08, c_nf_per_km=400.0, max_i_ka=0.125),
    "NAYY 4x35 SE": dict(r_ohm_per_km=0.87, x_ohm_per_km=0.08, c_nf_per_km=430.0, max_i_ka=0.150),
    "NAYY 4x50 SE": dict(r_ohm_per_km=0.64, x_ohm_per_km=0.08, c_nf_per_km=360.0, max_i_ka=0.170),
    "NAYY 4x70 SE": dict(r_ohm_per_km=0.44, x_ohm_per_km=0.08, c_nf_per_km=390.0, max_i_ka=0.215),
    "NAYY 4x95 SE": dict(r_ohm_per_km=0.32, x_ohm_per_km=0.08, c_nf_per_km=440.0, max_i_ka=0.260),
    "NAYY 4x120 SE": dict(r_ohm_per_km=0.25, x_ohm_per_km=0.08, c_nf_per_km=460.0, max_i_ka=0.300),
    "NAYY 4x150 SE": dict(r_ohm_per_km=0.21, x_ohm_per_km=0.08, c_nf_per_km=480.0, max_i_ka=0.340),
    "NAYY 4x185 SE": dict(r_ohm_per_km=0.16, x_ohm_per_km=0.08, c_nf_per_km=500.0, max_i_ka=0.385),
    "NAYY 4x240 SE": dict(r_ohm_per_km=0.13, x_ohm_per_km=0.08, c_nf_per_km=520.0, max_i_ka=0.450),
}

LINE_REQUIRED = ("r_ohm_per_km", "x_ohm_per_km", "c_nf_per_km", "max_i_ka")
TRAFO_REQUIRED = (
    "sn_mva", "vn_hv_kv", "vn_lv_kv", "vk_percent", "vkr_percent",
    "pfe_kw", "i0_percent", "shift_degree",
)

_ELEMENT_REQUIRED = {"line": LINE_REQUIRED, "trafo": TRAFO_REQUIRED}


def add_basic_std_types(net: pp.pandapowerNet) -> list[str]:
    """Register the bundled NAYY LV cable types on ``net``.

    Only types that are not already present are added. Returns the names of the
    added types.
    """
    added = []
    for name, params in NAYY_LV_CABLES.items():
        if not pp.std_types.std_type_exists(net, name, element="line"):
            pp.create_std_type(net, params, name, element="line")
            added.append(name)
    return added


def add_std_type(
    net: pp.pandapowerNet,
    name: str,
    params: dict,
    element: str = "line",
    overwrite: bool = True,
) -> str:
    """Add a single custom standard type (``element`` in {"line", "trafo"})."""
    if element not in _ELEMENT_REQUIRED:
        raise ValueError(f"element must be one of {sorted(_ELEMENT_REQUIRED)}")
    missing = [c for c in _ELEMENT_REQUIRED[element] if c not in params]
    if missing:
        raise ValueError(
            f"missing required parameter(s) for {element} std type {name!r}: {missing}"
        )
    pp.create_std_type(
        net, params, name, element=element, overwrite=overwrite, check_required=False
    )
    return name


def load_std_types_from_file(
    net: pp.pandapowerNet,
    path: str,
    element: str = "line",
    required: Optional[Sequence[str]] = None,
) -> list[str]:
    """Import custom standard types from an Excel workbook.

    Each row of the sheet is one standard type; the first column must be the
    type name and the remaining columns the parameter/value pairs. Unknown
    columns are ignored.

    Parameters
    ----------
    net : pandapower net
        The net the types are registered on.
    path : str
        Path to a ``.xlsx`` file.
    element : {"line", "trafo"}
        Element family the types belong to.
    required : sequence of str, optional
        Parameters that must be present. Defaults to the GridKit/pandapower
        required columns for ``element``.

    Returns
    -------
    list[str]
        Names of the imported standard types.
    """
    if not (required is None or all(c in _ELEMENT_REQUIRED[element] for c in required)):
        raise ValueError("GridKit only supports the pandapower required parameter set")

    df = _read_workbook(path)
    req = list(required) if required else list(_ELEMENT_REQUIRED[element])
    imported = []
    for row in df:
        name, params = row["name"], row["params"]
        if name is None or not name:
            raise ValueError(f"standard type entry without a name in {path}")
        missing = [c for c in req if c not in params]
        if missing:
            raise ValueError(f"{name!r} in {path} is missing {missing}")
        add_std_type(net, name, params, element=element)
        imported.append(name)
    return imported


def _read_workbook(path: str) -> list[dict]:
    """Read the first sheet of an xlsx file as a list of {name, params} rows."""
    import pandas as pd

    df = pd.read_excel(path)
    if "name" not in df.columns and df.shape[1] >= 1:
        df = df.rename(columns={df.columns[0]: "name"})
    if "name" not in df.columns:
        raise ValueError(f"workbook {path!r} needs a column named 'name'")
    rows = []
    for _, r in df.iterrows():
        name = r.get("name")
        params = {
            str(k): float(v)
            for k, v in r.drop(labels=["name"], errors="ignore").items()
            if pd.notna(v) and k in _ELEMENT_REQUIRED["line"] + ("g_us_per_km",)
        }
        rows.append({"name": name, "params": params})
    return rows
