"""Benchmark GridKit power-flow backends on a large network.

Compares repeated pandapower Newton-Raphson solves against the C++
lightsim2grid fast path, on `example_network_9241.xlsx` (a 9241-bus model).

Run with:  uv run python examples/benchmark_backends.py
"""

import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import plotly.graph_objects as go

import gridkit as gk

NETWORK_FILE = Path(__file__).resolve().parent.parent / "example_network_9241.xlsx"
RUNS = 20  # bump to 100 for a more representative benchmark


def main() -> None:
    network = gk.from_excel(str(NETWORK_FILE))
    print(
        f"loaded {NETWORK_FILE.name}: "
        f"{len(network.buses)} buses, {len(network.lines)} lines"
    )

    pandapower_backend = []
    print(f"\npandapower backend ({RUNS} runs) ...")
    for i in range(RUNS):
        start = time.time()
        network.runpp(max_iteration=1000)
        pandapower_backend.append(time.time() - start)

    lightsim2grid_backend = []
    print(f"lightsim2grid backend ({RUNS} runs) ...")
    for i in range(RUNS):
        start = time.time()
        network.runpp(max_iteration=1000, lightsim2grid=True, numba=False)
        lightsim2grid_backend.append(time.time() - start)

    def median_ms(values):
        return sorted(values)[len(values) // 2] * 1e3

    print(f"\npandapower    median: {median_ms(pandapower_backend):.1f} ms")
    print(f"lightsim2grid median: {median_ms(lightsim2grid_backend):.1f} ms")

    fig = go.Figure()
    fig.add_trace(go.Box(y=pandapower_backend, name="pandapower"))
    fig.add_trace(go.Box(y=lightsim2grid_backend, name="lightsim2grid"))
    fig.show()


if __name__ == "__main__":
    main()
