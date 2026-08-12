"""Power-flow backend abstraction.

GridKit can solve power flow either directly through pandapower
(:class:`PandaPowerBackend`) or by delegating the Newton-Raphson solve to a
``grid2op.Backend.PandaPowerBackend`` (:class:`Grid2OpBackend`). Both return a
:class:`SolveResult` so the caller does not care which engine produced it.

The Grid2Op path serializes the net once, loads it into the grid2op backend and
then hot-syncs loads/gens before every subsequent solve (no re-serialization),
which is the setup that matters for repeated control/optimization loops.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import pandapower as pp
import pandapower.powerflow as pp_pf

try:  # pandapower <3 or old layout
    from pandapower.powerflow import LoadflowNotConverged  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    LoadflowNotConverged = pp_pf.LoadflowNotConverged  # type: ignore[attr-defined]

logger = logging.getLogger(__name__)


@dataclass
class SolveResult:
    """Result of a power-flow run."""

    converged: bool
    solver: str
    iterations: int = 0
    elapsed_s: float = 0.0
    error: Optional[str] = None
    extra: dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.converged


class PowerFlowBackend(ABC):
    """Interface every GridKit power-flow backend implements."""

    name: str = "base"

    @abstractmethod
    def solve(
        self,
        net: pp.pandapowerNet,
        algorithm: str = "nr",
        max_iteration: int = 10,
        **kwargs,
    ) -> SolveResult:
        """Run a power flow on ``net`` and write the ``res_*`` tables back."""


class PandaPowerBackend(PowerFlowBackend):
    """Solve directly with ``pandapower.runpp``.

    Supports every algorithm pandapower ships (``nr``, ``nr_iv``, ``gs``,
    ``iwamoto_nr``, ``fdbx``, ``fdxb``) plus the optional C++ ``lightsim2grid``
    fast path, which is auto-disabled when the net is not compatible.
    """

    name = "pandapower"

    def __init__(self, lightsim2grid: bool = False, init: str = "auto", **pf_kwargs):
        self.lightsim2grid = lightsim2grid
        self.init = init
        self.pf_kwargs = dict(pf_kwargs)

    def solve(
        self,
        net: pp.pandapowerNet,
        algorithm: str = "nr",
        max_iteration: int = 10,
        **kwargs,
    ) -> SolveResult:
        lightsim2grid = kwargs.pop("lightsim2grid", self.lightsim2grid)
        if lightsim2grid and not _lightsim_compatible(net, algorithm):
            logger.info(
                "lightsim2grid requested but not compatible with this net "
                "(multiple slacks / algorithm / special elements) - falling back to NR"
            )
            lightsim2grid = False

        t0 = time.perf_counter()
        iterations = 0
        error: Optional[str] = None
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning)
                pp.runpp(
                    net,
                    algorithm=algorithm,
                    init=self.init,
                    max_iteration=max_iteration,
                    lightsim2grid=lightsim2grid,
                    **self.pf_kwargs,
                    **kwargs,
                )
            converged = True
        except LoadflowNotConverged as exc:
            converged = False
            error = str(exc)
        except Exception as exc:  # any solver failure -> not converged
            converged = False
            error = f"{type(exc).__name__}: {exc}"
        elapsed = time.perf_counter() - t0

        if converged and "_ppc" in net and "iterations" in net["_ppc"]:
            iterations = int(net["_ppc"]["iterations"])
        return SolveResult(
            converged=converged,
            solver=f"pandapower/{algorithm}"
            + ("+lightsim2grid" if lightsim2grid else ""),
            iterations=iterations,
            elapsed_s=elapsed,
            error=error,
        )


class Grid2OpBackend(PowerFlowBackend):
    """Solve the Newton-Raphson power flow through a grid2op backend.

    The net is serialized once and loaded into a
    ``grid2op.Backend.PandaPowerBackend``; afterwards the load/gen injections
    are hot-synced before each solve so repeated runs avoid re-serialization.
    Only the ``nr`` algorithm is supported by grid2op's backend; anything else
    falls back to :class:`PandaPowerBackend`.

    .. note::
       grid2op's backend injects an internal slack generator into its own copy
       of the net. GridKit only copies the ``res_*`` tables back, so the user's
       net is never polluted.

    Parameters
    ----------
    lightsim2grid : bool
        Ask pandapower (called by grid2op) to use the C++ lightsim2grid solver.
        Disabled automatically for nets with multiple slack sources, which the
        current grid2op+pandapower combination cannot handle.
    max_iter : int
        Default iteration budget for the grid2op backend.
    """

    name = "grid2op"

    def __init__(
        self,
        lightsim2grid: bool = False,
        max_iter: int = 10,
        detailed_infos_for_cascading_failures: bool = False,
        with_numba: bool = False,
        **backend_kwargs,
    ):
        self.lightsim2grid = lightsim2grid
        self.max_iter = max_iter
        self.backend_kwargs = dict(backend_kwargs)
        self.backend_kwargs.update(
            lightsim2grid=lightsim2grid,
            max_iter=max_iter,
            detailed_infos_for_cascading_failures=detailed_infos_for_cascading_failures,
            with_numba=with_numba,
        )
        self._backend = None
        self._n_bus = 0
        self._n_line = 0
        self._n_load = 0
        self._n_gen = 0
        self._tmpdir: Optional[tempfile.TemporaryDirectory] = None

    # -- lifecycle ---------------------------------------------------------
    def _ensure_loaded(self, net: pp.pandapowerNet) -> None:
        if self._backend is not None:
            return
        from grid2op.Backend import PandaPowerBackend  # deferred import

        self._tmpdir = tempfile.TemporaryDirectory(prefix="gridkit_")
        path = self._tmpdir.name
        filename = "grid.json"
        pp.to_json(net, os.path.join(path, filename))
        backend = PandaPowerBackend(**self.backend_kwargs)
        backend.load_grid(path, filename)
        self._backend = backend
        self._n_bus = len(net.bus)
        self._n_line = len(net.line)
        self._n_load = len(net.load)
        self._n_gen = len(net.gen)

    def _sync_inputs(self, net: pp.pandapowerNet) -> None:
        g = self._backend._grid
        g.bus.loc[: self._n_bus - 1, "in_service"] = net.bus["in_service"].values
        if self._n_load:
            g.load.loc[: self._n_load - 1, "p_mw"] = net.load["p_mw"].values
            g.load.loc[: self._n_load - 1, "q_mvar"] = net.load["q_mvar"].values
            g.load.loc[: self._n_load - 1, "in_service"] = net.load["in_service"].values
        if self._n_gen:
            g.gen.loc[: self._n_gen - 1, "p_mw"] = net.gen["p_mw"].values
            g.gen.loc[: self._n_gen - 1, "vm_pu"] = net.gen["vm_pu"].values
            g.gen.loc[: self._n_gen - 1, "in_service"] = net.gen["in_service"].values

    def _copy_results(self, net: pp.pandapowerNet) -> None:
        g = self._backend._grid
        net.res_bus = g.res_bus.iloc[: self._n_bus].reset_index(drop=True)
        if self._n_line:
            net.res_line = g.res_line.iloc[: self._n_line].reset_index(drop=True)
        if self._n_load:
            net.res_load = g.res_load.iloc[: self._n_load].reset_index(drop=True)
        if self._n_gen:
            net.res_gen = g.res_gen.iloc[: self._n_gen].reset_index(drop=True)
        if len(g.res_ext_grid):
            net.res_ext_grid = g.res_ext_grid.reset_index(drop=True)

    def close(self) -> None:
        if self._tmpdir is not None:
            self._tmpdir.cleanup()
            self._tmpdir = None
        self._backend = None

    # -- solving -----------------------------------------------------------
    def solve(
        self,
        net: pp.pandapowerNet,
        algorithm: str = "nr",
        max_iteration: int = 10,
        **kwargs,
    ) -> SolveResult:
        if algorithm != "nr":
            logger.warning(
                "grid2op backend only implements Newton-Raphson ('nr'); "
                "delegating algorithm=%r to pandapower", algorithm
            )
            return PandaPowerBackend(
                lightsim2grid=self.lightsim2grid
            ).solve(net, algorithm=algorithm, max_iteration=max_iteration, **kwargs)

        lightsim2grid = kwargs.pop("lightsim2grid", self.lightsim2grid)
        self._ensure_loaded(net)
        self._sync_inputs(net)
        t0 = time.perf_counter()
        error: Optional[str] = None
        try:
            converged, exc = self._backend.runpf(is_dc=False)
            if exc is not None:
                error = str(exc)
            if not converged:
                error = error or "power flow did not converge"
        except Exception as exc:  # pragma: no cover - defensive
            converged, error = False, f"{type(exc).__name__}: {exc}"
        elapsed = time.perf_counter() - t0
        if converged:
            self._copy_results(net)
        return SolveResult(
            converged=converged,
            solver="grid2op/PandaPowerBackend"
            + ("+lightsim2grid" if lightsim2grid else ""),
            iterations=0,
            elapsed_s=elapsed,
            error=error,
        )

    def __del__(self):  # pragma: no cover - best effort
        try:
            self.close()
        except Exception:
            pass


def _lightsim_compatible(net: pp.pandapowerNet, algorithm: str) -> bool:
    if algorithm != "nr":
        return False
    n_slack = len(net.ext_grid.query("in_service"))
    if "slack" in net.gen.columns:
        n_slack += len(net.gen.query("slack & in_service"))
    if n_slack > 1:
        return False
    if len(net.shunt) and "controllable" in net.shunt and any(
        net.shunt.controllable.fillna(False)
    ):
        return False
    for col in ("tcsc", "svc", "ssc", "vsc", "bus_dc", "line_dc"):
        table = getattr(net, col, None)
        if table is not None and len(table):
            return False
    return True
