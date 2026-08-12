"""Convergence diagnostics for power-flow failures.

When :meth:`gridkit.Network.runpp` does not converge, :func:`report` inspects
the net and explains the most probable causes in the style:

    Power flow did not converge (algorithm=nr, max_iteration=10).
    Probable causes:
    [1] Slack (ext_grid) present
      - ok (ext_grid on bus [0])
    ...
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

# --------------------------------------------------------------------- #
# data model                                                            #
# --------------------------------------------------------------------- #


class Check:
    """One diagnostic item: a status plus explanation lines."""

    def __init__(self, title: str, status: str, lines: Sequence[str]):
        self.title = title
        self.status = status  # "ok" | "warn" | "error"
        self.lines = list(lines)

    @property
    def is_bad(self) -> bool:
        return self.status in ("warn", "error")

    def render(self, idx: int) -> list[str]:
        out = [f"[{idx}] {self.title}"]
        prefix = {"ok": "- ok", "warn": "- warn", "error": "- error"}[self.status]
        for line in self.lines:
            out.append(f"  {prefix if line is None else line}")
        out.append("")
        return out


# --------------------------------------------------------------------- #
# individual checks                                                     #
# --------------------------------------------------------------------- #


def check_slack(network) -> Check:
    net = network.net
    title = "Slack (ext_grid) present"
    ext = net.ext_grid.query("in_service")
    slack_gens = net.gen.query("slack & in_service") if len(net.gen) else net.gen
    if len(ext) == 0 and len(slack_gens) == 0:
        return Check(title, "error", [None])
    if len(ext) + len(slack_gens) > 1:
        lines = ["- multiple slack sources:"]
        for _, row in ext.iterrows():
            lines.append(f"  - ext_grid on bus [{int(row['bus'])}]")
        for _, row in slack_gens.iterrows():
            lines.append(f"  - slack gen on bus [{int(row['bus'])}]")
        return Check(title, "warn", lines)
    bus = int(ext["bus"].iloc[0]) if len(ext) else int(slack_gens["bus"].iloc[0])
    return Check(title, "ok", [f"- ok (ext_grid on bus [{bus}])"])


def check_nan_inf(network) -> Check:
    net = network.net
    title = "NaN/Inf parameters"
    bad: list[str] = []
    for table in ("bus", "line", "load", "gen", "ext_grid", "trafo"):
        df = getattr(net, table)
        if len(df) == 0:
            continue
        numeric = df.select_dtypes(include=[np.number])
        if numeric.empty:
            continue
        mask = numeric.isna() | np.isinf(numeric)
        # a whole column of NaN is just an unset optional field (e.g. sn_mva)
        active = mask.columns[mask.any().values & ~mask.all().values]
        for c in active:
            count = int(mask[c].sum())
            bad.append(f"- {table}.{c}: {count} bad value(s)")
    if not bad:
        return Check(title, "ok", ["- ok (none)"])
    return Check(title, "error", bad)


def check_line_impedances(network, limits=None) -> Check:
    net = network.net
    limits = limits or dict(
        r_ohm_per_km=(0.001, 5.0),
        x_ohm_per_km=(0.001, 2.0),
        c_nf_per_km=(1.0, 2000.0),
    )
    title = "Line impedances (r/x/c per km)"
    if len(net.line) == 0:
        return Check(title, "warn", ["- no lines in the network"])
    bad: list[str] = []
    for col, (lo, hi) in limits.items():
        vals = net.line[col].to_numpy()
        good = (vals >= lo) & (vals <= hi)
        if not good.all():
            names = [
                _lname(net, i) or f"line {i}"
                for i in np.where(~good)[0].tolist()
            ][:8]
            bad.append(
                f"- {col} outside ({lo}, {hi}): {', '.join(map(str, names))}"
            )
    if bad:
        return Check(title, "error", bad)
    r = net.line["r_ohm_per_km"]
    x = net.line["x_ohm_per_km"]
    c = net.line["c_nf_per_km"]
    lo_r, hi_r = limits["r_ohm_per_km"]
    return Check(
        title,
        "ok",
        [
            f"- ok (within r={_fmt_range(r, lo_r, hi_r)}, "
            f"x={_fmt_range(x, *limits['x_ohm_per_km'])}, "
            f"c={_fmt_range(c, *limits['c_nf_per_km'])})"
        ],
    )


def check_load_vs_line(network) -> Check:
    net = network.net
    title = "Load vs. line capacity"
    if len(net.load) == 0:
        return Check(title, "ok", ["- no loads"])
    if len(net.line) == 0:
        return Check(title, "warn", ["- no lines to compare against"])

    bus_vn = net.bus["vn_kv"]
    line_rated = _line_rating_by_bus(net)  # bus index -> (max_i_ka, line index)
    bad: list[Tuple[int, str]] = []

    for lidx, row in net.load.iterrows():
        if not row.get("in_service", True):
            continue
        bus = int(row["bus"])
        vn = bus_vn.loc[bus]
        s_mva = np.hypot(row["p_mw"] * row.get("scaling", 1.0),
                         row["q_mvar"] * row.get("scaling", 1.0))
        need_a = _needed_current(s_mva, vn)
        entry = line_rated.get(bus)
        pct = None
        if entry is not None:
            rated_a, _ = entry
            pct = need_a / rated_a * 100.0 if rated_a else np.inf
        bad.append((bus, _fmt_load_line(row, bus, vn, need_a, pct)))

    lines = []
    for bus, text in sorted(bad, key=lambda t: t[0]):
        lines.append(f"- {text}")

    total_load = float(net.load["p_mw"].mul(net.load["scaling"], fill_value=1).sum())
    total_gen = float(net.gen["p_mw"].sum()) if len(net.gen) else 0.0
    vn_vals = bus_vn.unique()
    vn = vn_vals[0] if len(vn_vals) == 1 else None
    vn_txt = f" on a {vn * 1000:.0f} V feeder" if vn and vn < 1 else ""
    lines.append(
        f"- total load {total_load * 1000:,.0f} kW vs. generation {total_gen * 1000:,.0f} kW{vn_txt}"
    )
    if vn and vn < 1.0 and total_load > 0.05:
        lines.append(
            "- loads look far beyond what an LV feeder can carry - if the data is in kW, "
            "p_mw was filled with MW numbers ~1000x too large. Check units (kW -> 0.001 MW) "
            "or generator placement."
        )

    over = [t for _, t in bad if "over rated" in t]
    status = "error" if over else ("warn" if any("warn" in t for _, t in bad) else "ok")
    if not bad:
        status = "ok"
    return Check(title, status, lines)


def check_voltage_drop(network) -> Check:
    net = network.net
    title = "Estimated voltage drop"
    if len(net.line) == 0 or len(net.load) == 0:
        return Check(title, "ok", ["- nothing to estimate"])
    ext = net.ext_grid.query("in_service")
    slack_buses = set(ext["bus"].tolist()) | set(
        net.gen.query("slack & in_service")["bus"].tolist()
    )
    if not slack_buses:
        return Check(title, "error", ["- no slack bus; voltage drop is undefined"])

    g = _netx_graph(net)
    worst: list[Tuple[float, str]] = []
    for _, row in net.load.iterrows():
        if not row.get("in_service", True):
            continue
        bus = int(row["bus"])
        path = _shortest_path(g, slack_buses, bus)
        if path is None:
            continue
        s_mva = np.hypot(row["p_mw"] * row.get("scaling", 1.0),
                         row["q_mvar"] * row.get("scaling", 1.0))
        vn = net.bus.loc[bus, "vn_kv"]
        drop = _estimate_drop(path, net, s_mva, vn)
        worst.append((drop, _lname(net, bus) or f"bus {bus}"))

    if not worst:
        return Check(title, "warn", ["- loads not connected to the slack component"])
    worst.sort(reverse=True)
    lines = []
    for drop, name in worst[:5]:
        lines.append(f"- {name}: ~{drop * 100:.1f}% voltage drop")
    top = worst[0][0]
    status = "error" if top > 0.05 else ("warn" if top > 0.03 else "ok")
    if status == "ok":
        lines = [f"- ok (worst ~{top * 100:.1f}% at {worst[0][1]})"]
    return Check(title, status, lines)


# --------------------------------------------------------------------- #
# report                                                                #
# --------------------------------------------------------------------- #


def report(network, algorithm: str = "nr", max_iteration: int = 10) -> str:
    """Return the full diagnostic report (also logs it at warning level)."""
    checks = [
        check_slack(network),
        check_nan_inf(network),
        check_line_impedances(network),
        check_load_vs_line(network),
        check_voltage_drop(network),
    ]
    bad = [c for c in checks if c.is_bad]

    out: list[str] = [
        f"Power flow did not converge (algorithm={algorithm}, max_iteration={max_iteration}).",
        "Probable causes:",
        "",
    ]
    for i, c in enumerate(checks, 1):
        out.extend(c.render(i))
    out.append("  ___________ END OF PANDAPOWER DIAGNOSTIC ___________")
    out.append("")
    if bad:
        cause = next((ln for ln in bad[0].lines if ln is not None), bad[0].title)
        out.append(f"Most likely cause: {cause.lstrip('- ').strip()}")
    out.append(
        "Fix the issues above (units / parameters / topology), then re-run. "
        "Increasing max_iteration rarely helps when the problem is a bad network state."
    )
    return "\n".join(out).replace("\n \n", "\n\n")


# --------------------------------------------------------------------- #
# helpers                                                               #
# --------------------------------------------------------------------- #


def _lname(net, idx) -> Optional[str]:
    try:
        return str(net.bus.loc[idx, "name"]) if pd.notna(net.bus.loc[idx, "name"]) else None
    except Exception:
        return None


def _fmt_range(vals: pd.Series, lo: float, hi: float) -> str:
    return f"({lo}, {hi})" if len(vals) else "(n/a)"


def _needed_current(s_mva: float, vn_kv: float) -> float:
    if vn_kv <= 0:
        return 0.0
    return s_mva * 1e6 / (np.sqrt(3.0) * vn_kv * 1e3)


def _line_rating_by_bus(net) -> dict[int, Tuple[float, int]]:
    """bus index -> (smallest thermal rating in A among incident lines, line index)."""
    best: dict[int, Tuple[float, int]] = {}
    for lidx, row in net.line.iterrows():
        rated_a = float(row["max_i_ka"]) * 1000.0 * row.get("parallel", 1.0)
        for bus in (int(row["from_bus"]), int(row["to_bus"])):
            cur = best.get(bus)
            if cur is None or rated_a < cur[0]:
                best[bus] = (rated_a, int(lidx))
    return best


def _fmt_load_line(row: pd.Series, bus: int, vn: float, need_a: float, pct: Optional[float]):
    p_kw = row["p_mw"] * row.get("scaling", 1.0) * 1000.0
    name = row.get("name") if pd.notna(row.get("name")) else bus
    head = f"bus {name} ({bus}): {p_kw:,.0f} kW -> needs ~{need_a:,.0f} A"
    if pct is None:
        return f"{head}, no incident line"
    rated_a = need_a / (pct / 100.0)
    tag = "  <-- over rated!" if pct > 100 else ("  <-- close to limit!" if pct > 80 else "")
    return f"{head}, nearest line rated {rated_a:,.0f} A ({pct:,.0f}%){tag}"


def _netx_graph(net):
    import networkx as nx

    g = nx.Graph()
    for _, row in net.bus.iterrows():
        g.add_node(int(row.name))
    for _, row in net.line.iterrows():
        fb, tb = int(row["from_bus"]), int(row["to_bus"])
        weight = np.hypot(
            row["r_ohm_per_km"] * row["length_km"],
            row["x_ohm_per_km"] * row["length_km"],
        )
        g.add_edge(fb, tb, weight=weight, line=int(row.name))
    return g


def _shortest_path(g, sources, target):
    import networkx as nx

    return nx.shortest_path(g, source=min(sources), target=target, weight="weight")


def _estimate_drop(path, net, s_mva: float, vn_kv: float) -> float:
    if len(path) < 2:
        return 0.0
    z_sum = 0j
    for a, b in zip(path[:-1], path[1:]):
        found = None
        for _, row in net.line.iterrows():
            fb, tb = int(row["from_bus"]), int(row["to_bus"])
            if {fb, tb} == {a, b}:
                found = row
                break
        if found is None:
            continue
        z = (found["r_ohm_per_km"] + 1j * found["x_ohm_per_km"]) * found["length_km"]
        z_sum += z
    base = (vn_kv * 1e3) ** 2
    return float(np.abs((s_mva * 1e6) * z_sum / base)) if base else 0.0
