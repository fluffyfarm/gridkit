"""Regenerate the example_network_*.xlsx workbooks from pandapower's cases.

Pulls the 300-bus, 1354-bus and 9241-bus benchmark cases and writes each to
Excel (including results) at the repository root — the files used by
`examples/benchmark_backends.py`.

Run with:  uv run python examples/make_example_networks.py
"""

import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import pandapower as pp
from pandapower.networks import case300, case9241pegase, case1354pegase

OUT_DIR = Path(__file__).resolve().parent.parent


def main() -> None:
    cases = [
        ("example_network_300.xlsx", case300),
        ("example_network_1354.xlsx", case1354pegase),
        ("example_network_9241.xlsx", case9241pegase),
    ]
    for filename, builder in cases:
        path = OUT_DIR / filename
        print(f"building {filename} ...", flush=True)
        pp.to_excel(builder(), str(path), include_results=True)
        print(f"  wrote {path}", flush=True)


if __name__ == "__main__":
    main()
