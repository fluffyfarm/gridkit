"""Plotly helpers for GridKit networks.

Both helpers return a ``plotly.graph_objects.Figure`` and never auto-display it,
so you can build several figures and call ``.show()`` yourself once per figure
(avoids the "figure shown twice" annoyance in notebooks).
"""

from __future__ import annotations

from typing import Any, Optional


def simple_plotly(
    network,
    show: bool = False,
    bus_size: float = 10.0,
    line_width: float = 1.0,
    title: Optional[str] = None,
    **kwargs,
) -> Any:
    """Plot the network topology with bus names as hover labels."""
    import pandapower.plotting as plot

    _ensure_geodata(network)
    fig = plot.simple_plotly(
        network.net,
        bus_size=bus_size,
        line_width=line_width,
        filename=None,
        showlegend=True,
        **kwargs,
    )
    if title:
        fig.update_layout(title=title)
    if show:
        fig.show()
    return fig


def pf_res_plotly(
    network,
    show: bool = False,
    bus_size: float = 10.0,
    line_width: float = 2.0,
    title: Optional[str] = None,
    **kwargs,
) -> Any:
    """Plot power-flow results: voltages at buses, loading on lines."""
    import pandapower.plotting as plot

    if network.converged is not True:
        raise RuntimeError(
            "pf_res_plotly requires a converged power flow - run net.runpp() first"
        )
    _ensure_geodata(network)
    fig = plot.pf_res_plotly(
        network.net,
        bus_size=bus_size,
        line_width=line_width,
        filename=None,
        **kwargs,
    )
    if title:
        fig.update_layout(title=title)
    if show:
        fig.show()
    return fig


def _ensure_geodata(network) -> None:
    """Give every bus plot coordinates so plotly can draw the net.

    Coordinates live in ``net.bus['geo']`` (GeoJSON string) in pandapower 3.x.
    User-provided ``geo_location`` values are kept; missing buses are placed on
    a circle (no igraph required).
    """
    import math

    import numpy as np

    net = network.net
    missing = [int(i) for i, g in net.bus["geo"].items() if g is None]
    if not missing:
        return
    n = len(net.bus)
    for k, i in enumerate(missing):
        angle = 2.0 * math.pi * k / max(len(missing), 1)
        r = 1.0 + 0.05 * k
        net.bus.loc[i, "geo"] = (
            f'{{"coordinates":[{r * math.cos(angle):.6f},'
            f"{r * math.sin(angle):.6f}], \"type\":\"Point\"}}"
        )
