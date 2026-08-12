"""Domain-oriented network construction API.

GridKit wraps a pandapower net but exposes *names* (``"PV_01"``, ``"LINE_01"``)
instead of integer indices. Every element created through the :class:`Network`
API can later be referenced by its name, while :attr:`Network.net` gives access
to the underlying pandapower net for advanced use.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional, Tuple, Union

import pandapower as pp
import pandapower.std_types as pp_std_types
import numpy as np
import pandas as pd

from . import std_types as gk_std_types
from .backends import (
    Grid2OpBackend,
    PandaPowerBackend,
    PowerFlowBackend,
    SolveResult,
)

logger = logging.getLogger(__name__)

Geo = Optional[Tuple[float, float]]


def create_empty_network() -> "Network":
    """Create an empty :class:`Network` (GridKit's ``pp.create_empty_network``)."""
    return Network()


def from_excel(path: str) -> "Network":
    """Create a :class:`Network` from a pandapower-style Excel workbook."""
    return Network.from_excel(path)


def from_json(path: str) -> "Network":
    """Create a :class:`Network` from a pandapower-style JSON file."""
    return Network.from_json(path)


class Network:
    """A named, domain-oriented power network over a pandapower net.

    Examples
    --------
    >>> net = create_empty_network()
    >>> net.add_bus("PV_01", vn_kv=0.4, geo_location=(10.0, 20.0))
    >>> net.add_bus("LOAD_01", vn_kv=0.4)
    >>> net.add_line("LINE_01", from_bus="PV_01", to_bus="LOAD_01",
    ...              length_km=0.1, std_type="NAYY 4x50 SE")
    >>> net.add_load("LOAD", bus="LOAD_01", p_mw=0.05)
    >>> net.runpp()
    """

    def __init__(self, net: Optional[pp.pandapowerNet] = None):
        self._net = net if net is not None else pp.create_empty_network()
        self._backend: Optional[PowerFlowBackend] = None
        # name -> index maps (populated lazily, kept in sync on each build call)
        self._buses: dict[str, int] = {}
        self._lines: dict[str, int] = {}
        self._loads: dict[str, int] = {}
        self._gens: dict[str, int] = {}
        self._ext_grids: dict[str, int] = {}
        self._trafos: dict[str, int] = {}
        self._sgens: dict[str, int] = {}
        self._maps: dict = {}
        self._rebuild_index()
        gk_std_types.add_basic_std_types(self._net)

    # ------------------------------------------------------------------ #
    #  access                                                            #
    # ------------------------------------------------------------------ #
    @property
    def net(self) -> pp.pandapowerNet:
        """The underlying pandapower net."""
        return self._net

    @property
    def buses(self) -> pd.DataFrame:
        return self._net.bus

    @property
    def lines(self) -> pd.DataFrame:
        return self._net.line

    @property
    def loads(self) -> pd.DataFrame:
        return self._net.load

    @property
    def gens(self) -> pd.DataFrame:
        return self._net.gen

    @property
    def ext_grids(self) -> pd.DataFrame:
        return self._net.ext_grid

    def bus_index(self, bus: object) -> int:
        """Resolve a bus name (or raw index) to its pandapower index."""
        return self._resolve(self._buses, "bus", bus)

    def bus_name(self, index: int) -> Optional[str]:
        row = self._net.bus.loc[index]
        return row.get("name") if isinstance(row, pd.Series) else None

    def line_index(self, name: object) -> int:
        return self._resolve(self._lines, "line", name)

    def load_index(self, name: object) -> int:
        return self._resolve(self._loads, "load", name)

    def gen_index(self, name: object) -> int:
        return self._resolve(self._gens, "gen", name)

    def ext_grid_index(self, name: object) -> int:
        return self._resolve(self._ext_grids, "ext_grid", name)

    def trafo_index(self, name: object) -> int:
        return self._resolve(self._trafos, "trafo", name)

    def sgen_index(self, name: object) -> int:
        return self._resolve(self._sgens, "sgen", name)

    @staticmethod
    def _resolve(mapping: dict, kind: str, key: object) -> int:
        if isinstance(key, (int, np.integer)) and key in mapping.values():
            return int(key)
        if key in mapping:
            return mapping[key]
        raise KeyError(f"no {kind} named {key!r}")

    def _rebuild_index(self) -> None:
        self._buses = _name_index(self._net.bus)
        self._lines = _name_index(self._net.line)
        self._loads = _name_index(self._net.load)
        self._gens = _name_index(self._net.gen)
        self._ext_grids = _name_index(self._net.ext_grid)
        self._trafos = _name_index(self._net.trafo)
        self._maps = dict(
            bus=self._buses,
            line=self._lines,
            load=self._loads,
            gen=self._gens,
            ext_grid=self._ext_grids,
            trafo=self._trafos,
        )

    def _register(self, table: str, name: str, index: int) -> str:
        if name in self._buses and table == "bus":
            raise ValueError(f"a bus named {name!r} already exists")
        self._maps[table][name] = index
        return name

    # ------------------------------------------------------------------ #
    #  construction                                                       #
    # ------------------------------------------------------------------ #
    def add_bus(
        self,
        name: str,
        vn_kv: float = 10.0,
        geo_location: Geo = None,
        zone: Optional[str] = None,
        in_service: bool = True,
        **kwargs,
    ) -> str:
        """Add a bus. ``geo_location=(x, y)`` sets its plot coordinates."""
        idx = pp.create_bus(
            self._net,
            vn_kv=vn_kv,
            name=name,
            geodata=geo_location,
            zone=zone,
            in_service=in_service,
            **kwargs,
        )
        self._register("bus", name, idx)
        return name

    def add_line(
        self,
        name: str,
        from_bus: object,
        to_bus: object,
        length_km: float,
        std_type: Optional[str] = None,
        r_ohm_per_km: Optional[float] = None,
        x_ohm_per_km: Optional[float] = None,
        c_nf_per_km: Optional[float] = None,
        max_i_ka: Optional[float] = None,
        g_us_per_km: float = 0.0,
        in_service: bool = True,
        geodata: Optional[Iterable[Tuple[float, float]]] = None,
        **kwargs,
    ) -> str:
        """Add a line between two buses (referenced by name or index).

        Pass ``std_type="NAYY 4x50 SE"`` for a standard type, or provide the
        four per-km parameters (``r_``/``x_``/``c_``/``max_i``) directly.
        """
        f, t = self.bus_index(from_bus), self.bus_index(to_bus)
        custom = {
            k: v
            for k, v in (
                ("r_ohm_per_km", r_ohm_per_km),
                ("x_ohm_per_km", x_ohm_per_km),
                ("c_nf_per_km", c_nf_per_km),
                ("max_i_ka", max_i_ka),
            )
            if v is not None
        }
        if std_type is not None:
            if not pp_std_types.std_type_exists(self._net, std_type, element="line"):
                raise KeyError(
                    f"unknown line std_type {std_type!r} "
                    f"(use add_std_type / load_std_types_from_file to add it)"
                )
            idx = pp.create_line(
                self._net,
                f,
                t,
                length_km,
                std_type=std_type,
                name=name,
                geodata=geodata,
                in_service=in_service,
                **kwargs,
            )
        elif len(custom) == 4:
            idx = pp.create_line_from_parameters(
                self._net,
                f,
                t,
                length_km,
                r_ohm_per_km=custom["r_ohm_per_km"],
                x_ohm_per_km=custom["x_ohm_per_km"],
                c_nf_per_km=custom["c_nf_per_km"],
                max_i_ka=custom["max_i_ka"],
                g_us_per_km=g_us_per_km,
                name=name,
                geodata=geodata,
                in_service=in_service,
                **kwargs,
            )
        else:
            raise ValueError(
                "add_line requires either std_type or all of "
                "r_ohm_per_km, x_ohm_per_km, c_nf_per_km, max_i_ka"
            )
        self._register("line", name, idx)
        return name

    def add_load(
        self,
        name: str,
        bus: object,
        p_mw: float = 0.0,
        q_mvar: float = 0.0,
        scaling: float = 1.0,
        in_service: bool = True,
        **kwargs,
    ) -> str:
        idx = pp.create_load(
            self._net,
            self.bus_index(bus),
            p_mw=p_mw,
            q_mvar=q_mvar,
            name=name,
            scaling=scaling,
            in_service=in_service,
            **kwargs,
        )
        self._register("load", name, idx)
        return name

    def add_gen(
        self,
        name: str,
        bus: object,
        p_mw: float = 0.0,
        vm_pu: float = 1.0,
        min_p_mw: float = 0.0,
        max_p_mw: Optional[float] = None,
        min_q_mvar: float = -999.0,
        max_q_mvar: float = 999.0,
        slack: bool = False,
        in_service: bool = True,
        **kwargs,
    ) -> str:
        idx = pp.create_gen(
            self._net,
            self.bus_index(bus),
            p_mw=p_mw,
            vm_pu=vm_pu,
            name=name,
            min_p_mw=min_p_mw,
            max_p_mw=max_p_mw,
            min_q_mvar=min_q_mvar,
            max_q_mvar=max_q_mvar,
            slack=slack,
            in_service=in_service,
            **kwargs,
        )
        self._register("gen", name, idx)
        return name

    def add_sgen(
        self,
        name: str,
        bus: object,
        p_mw: float = 0.0,
        q_mvar: float = 0.0,
        in_service: bool = True,
        **kwargs,
    ) -> str:
        """Add a static generator (PQ node, e.g. an inverter at fixed P/Q)."""
        idx = pp.create_sgen(
            self._net,
            self.bus_index(bus),
            p_mw=p_mw,
            q_mvar=q_mvar,
            name=name,
            in_service=in_service,
            **kwargs,
        )
        self._sgens.setdefault(name, idx)
        return name

    def add_ext_grid(
        self,
        name: str,
        bus: object,
        vm_pu: float = 1.0,
        va_degree: float = 0.0,
        in_service: bool = True,
        **kwargs,
    ) -> str:
        idx = pp.create_ext_grid(
            self._net,
            self.bus_index(bus),
            vm_pu=vm_pu,
            va_degree=va_degree,
            name=name,
            in_service=in_service,
            **kwargs,
        )
        self._register("ext_grid", name, idx)
        return name

    def add_trafo(
        self,
        name: str,
        hv_bus: object,
        lv_bus: object,
        std_type: str,
        in_service: bool = True,
        **kwargs,
    ) -> str:
        if not pp_std_types.std_type_exists(self._net, std_type, element="trafo"):
            raise KeyError(f"unknown trafo std_type {std_type!r}")
        pp.create_transformer(
            self._net,
            self.bus_index(hv_bus),
            self.bus_index(lv_bus),
            std_type=std_type,
            name=name,
            in_service=in_service,
            **kwargs,
        )
        self._register("trafo", name, len(self._net.trafo) - 1)
        return name

    # ------------------------------------------------------------------ #
    #  std types                                                          #
    # ------------------------------------------------------------------ #
    def add_std_type(
        self,
        name: str,
        params: dict,
        element: str = "line",
        overwrite: bool = True,
    ) -> str:
        return gk_std_types.add_std_type(
            self._net, name, params, element=element, overwrite=overwrite
        )

    def load_std_types_from_file(self, path: str, element: str = "line") -> list[str]:
        return gk_std_types.load_std_types_from_file(self._net, path, element=element)

    def available_std_types(self, element: str = "line") -> list[str]:
        return sorted(self._net.std_types[element])

    # ------------------------------------------------------------------ #
    #  serialization                                                      #
    # ------------------------------------------------------------------ #
    def to_json(self, path: str) -> None:
        pp.to_json(self._net, path)

    @classmethod
    def from_json(cls, path: str) -> "Network":
        return cls(pp.from_json(path))

    def to_excel(self, path: str) -> None:
        """Serialize the network to a pandapower-style Excel workbook."""
        pp.to_excel(self._net, path)

    @classmethod
    def from_excel(cls, path: str) -> "Network":
        """Load a network from a pandapower-style Excel workbook.

        The workbook is a ``pp.to_excel``-compatible file: one sheet per
        element table (``bus``, ``load``, ``line``, ...). Both GridKit names
        and raw pandapower indices are usable afterwards.
        """
        return cls(pp.from_excel(path))

    # ------------------------------------------------------------------ #
    #  power flow                                                         #
    # ------------------------------------------------------------------ #
    def runpp(
        self,
        algorithm: str = "nr",
        max_iteration: int = 10,
        backend: Optional[Union[str, PowerFlowBackend]] = None,
        **kwargs,
    ) -> SolveResult:
        """Run a power flow and store the ``res_*`` tables on the net.

        Parameters
        ----------
        algorithm : str
            One of pandapower's solvers: ``nr``, ``nr_iv``, ``gs``,
            ``iwamoto_nr``, ``fdbx``, ``fdxb``.
        max_iteration : int
            Iteration budget before declaring divergence.
        backend : str or PowerFlowBackend
            ``"pandapower"`` (default) or ``"grid2op"``, or a custom
            :class:`~gridkit.backends.PowerFlowBackend` instance.

        Returns
        -------
        SolveResult
            Convergence flag, solver used, iteration count and error message.
        """
        backend = self._get_backend(backend)
        self._rebuild_index()
        result = backend.solve(
            self._net, algorithm=algorithm, max_iteration=max_iteration, **kwargs
        )
        self._converged = result.converged
        if not result.converged:
            from . import diagnostics

            report = diagnostics.report(
                self, algorithm=algorithm, max_iteration=max_iteration
            )
            logger.warning("%s", report)
        return result

    def _get_backend(self, backend: Optional[Union[str, PowerFlowBackend]]):
        if backend is None:
            if self._backend is None:
                self._backend = PandaPowerBackend()
            return self._backend
        if isinstance(backend, PowerFlowBackend):
            return backend
        if isinstance(backend, str):
            if backend == "pandapower":
                return PandaPowerBackend()
            if backend == "grid2op":
                return Grid2OpBackend()
        raise ValueError(f"unknown backend {backend!r} (use 'pandapower', 'grid2op', "
                         "or a PowerFlowBackend instance)")

    @property
    def converged(self) -> Optional[bool]:
        """Convergence flag of the last :meth:`runpp` call (None if never run)."""
        return getattr(self, "_converged", None)

    # ------------------------------------------------------------------ #
    #  plotting                                                           #
    # ------------------------------------------------------------------ #
    def simple_plotly(self, show: bool = False, **kwargs):
        """Plot the topology. Returns a plotly figure; auto-show only on demand."""
        from .plotting import simple_plotly

        return simple_plotly(self, show=show, **kwargs)

    def pf_res_plotly(self, show: bool = False, **kwargs):
        """Plot power-flow results. Returns a plotly figure; auto-show on demand."""
        from .plotting import pf_res_plotly

        return pf_res_plotly(self, show=show, **kwargs)


# ---------------------------------------------------------------------- #
# helpers                                                                #
# ---------------------------------------------------------------------- #
def _name_index(df: pd.DataFrame) -> dict[str, int]:
    out: dict[str, int] = {}
    if "name" not in df.columns or len(df) == 0:
        return out
    for index, name in df["name"].items():
        if pd.isna(name) or str(name).strip() == "":
            continue
        out[str(name)] = int(index)
    return out
