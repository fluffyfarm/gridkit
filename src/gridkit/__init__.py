"""GridKit - a simple, extensible toolkit for power-grid modeling.

Example
-------
>>> import gridkit as gk
>>> net = gk.create_empty_network()
>>> net.add_bus("PV_01", vn_kv=0.4, geo_location=(0, 0))
>>> net.add_bus("LOAD_01", vn_kv=0.4, geo_location=(1, 0))
>>> net.add_line("LINE_01", from_bus="PV_01", to_bus="LOAD_01",
...              length_km=0.1, std_type="NAYY 4x50 SE")
>>> net.add_load("LOAD", bus="LOAD_01", p_mw=0.05)
>>> net.runpp()
"""

from .network import Network, create_empty_network, from_excel, from_json
from .backends import (
    Grid2OpBackend,
    PandaPowerBackend,
    PowerFlowBackend,
    SolveResult,
)
from . import diagnostics, plotting, std_types

__version__ = "0.1.0"

__all__ = [
    "Network",
    "create_empty_network",
    "from_excel",
    "from_json",
    "PowerFlowBackend",
    "PandaPowerBackend",
    "Grid2OpBackend",
    "SolveResult",
    "diagnostics",
    "plotting",
    "std_types",
    "__version__",
]
