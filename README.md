# GridKit

A simple, extensible toolkit for power-grid modeling, simulation, and control.

GridKit wraps **pandapower** behind a domain-oriented API and uses **Grid2Op**
as an optional power-flow backend, so you describe a grid with *names*
(`"PV_01"`, `"LOAD_01"`, `"SUB_01"`) instead of integer bus indices.

```python
import gridkit as gk

net = gk.create_empty_network()
net.add_bus("PV_01",    vn_kv=0.4, geo_location=(0.0, 0.0))
net.add_bus("BESS_01",  vn_kv=0.4, geo_location=(0.2, 0.1))
net.add_bus("LOAD_01",  vn_kv=0.4, geo_location=(0.4, 0.2))

net.add_ext_grid("GRID", bus="PV_01", vm_pu=1.0)
net.add_gen("PV", bus="PV_01", p_mw=0.03)
net.add_line("L1", from_bus="PV_01", to_bus="BESS_01",
             length_km=0.15, std_type="NAYY 4x50 SE")
net.add_load("LOAD", bus="LOAD_01", p_mw=0.035, q_mvar=0.005)

res = net.runpp()            # pandapower backend (default)
res = net.runpp(backend="grid2op")   # grid2op.Backend.PandaPowerBackend
net.pf_res_plotly()          # returns a plotly Figure (no auto-show)
```

## Features

- **Named elements** — buses, lines, loads, gens, sgens, ext grids and
  transformers are referenced by name; the underlying pandapower net stays
  available at `net.net`.
- **Standard line types** — `"NAYY 4x50 SE"` and friends work out of the box;
  add your own with `net.add_std_type(...)` or import a catalog from an Excel
  workbook with `net.load_std_types_from_file("types.xlsx")`.
- **Two power-flow backends**
  - `PandaPowerBackend` (default): direct `pandapower.runpp`, supports every
    algorithm (`nr`, `nr_iv`, `gs`, `iwamoto_nr`, `fdbx`, `fdxb`) and the
    optional C++ `lightsim2grid` fast path.
  - `Grid2OpBackend`: delegates the Newton-Raphson solve to
    `grid2op.Backend.PandaPowerBackend`. The net is serialized once, then loads
    and gens are hot-synced before every solve — ideal for repeated
    control/optimization loops.
- **Convergence diagnostics** — on divergence, `runpp` prints a structured
  report: slack presence, NaN/Inf parameters, line-impedance sanity, load vs.
  line capacity, estimated voltage drop, and a "most likely cause" verdict.
- **Plotting** — `net.simple_plotly()` and `net.pf_res_plotly()` return plotly
  figures without auto-showing, so you can build both and call `.show()` once.

## Installation

```bash
uv sync            # creates .venv and installs dependencies
uv run pytest -q   # run the test suite
uv run python examples/demo.py
```

## Custom standard types from Excel

Prepare a workbook whose first sheet has one row per type and a `name` column:

| name          | r_ohm_per_km | x_ohm_per_km | c_nf_per_km | max_i_ka |
|---------------|--------------|--------------|-------------|----------|
| MY CABLE 4x35 | 0.87         | 0.08         | 430         | 0.15     |

```python
net.load_std_types_from_file("types.xlsx")   # registers MY CABLE 4x35 ...
net.add_line("L", from_bus="A", to_bus="B", length_km=1.0, std_type="MY CABLE 4x35")
```

## Backend selection

`runpp(algorithm=..., max_iteration=..., backend=...)`:

```python
net.runpp()                          # pandapower, NR
net.runpp(algorithm="gs")            # Gauss-Seidel via pandapower
net.runpp(backend="grid2op")         # NR via grid2op backend (cached, hot-synced)
from gridkit import Grid2OpBackend
net.runpp(backend=Grid2OpBackend())  # or a reusable instance across nets
```

### Fast solver: lightsim2grid

For a large speed-up on big nets, pass `lightsim2grid=True` to use the C++
Newton-Raphson solver:

```python
net.runpp(lightsim2grid=True)        # pandapower NR via lightsim2grid (C++)
net.runpp(backend="grid2op", lightsim2grid=True)

from gridkit import PandaPowerBackend
net.runpp(backend=PandaPowerBackend(lightsim2grid=True))  # reusable instance
```

`lightsim2grid` is only used with `algorithm="nr"` and nets with at most one
slack source; otherwise GridKit automatically falls back to plain NR with a log
message. If the package is missing, install it with
`pip install lightsim2grid`.

Notes:

- The grid2op backend only implements Newton-Raphson; other algorithms fall
  back to pandapower with a warning.
- `lightsim2grid` is auto-disabled for nets the current
  grid2op+pandapower combination cannot handle (multiple slack sources).

## Layout

```
src/gridkit/
  network.py        Network builder API (add_bus, add_line, ... runpp, plotting)
  backends.py       PowerFlowBackend, PandaPowerBackend, Grid2OpBackend
  diagnostics.py    non-convergence report
  std_types.py      NAYY cable catalog + Excel import
  plotting.py       simple_plotly / pf_res_plotly wrappers
tests/              pytest suite
examples/demo.py    end-to-end demo (also shows the diagnostics report)
examples/benchmark_backends.py     pandapower vs. lightsim2grid timings on the 9241-bus case
examples/make_example_networks.py  regenerate the example_network_*.xlsx workbooks
```
