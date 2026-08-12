"""GridKit demo: build a small LV feeder with NAYY cables and run power flow.

Run with:  uv run python examples/demo.py
"""

import warnings

warnings.filterwarnings("ignore")

import gridkit as gk


def main() -> None:
    net = gk.create_empty_network()

    # --- buses ------------------------------------------------------------
    net.add_bus("SUB_01", vn_kv=0.4, geo_location=(0, 0))
    net.add_bus("PV_01", vn_kv=0.4, geo_location=(0.1, 0.2))
    net.add_bus("BESS_01", vn_kv=0.4, geo_location=(0.3, 0.25))
    net.add_bus("LOAD_01", vn_kv=0.4, geo_location=(0.4, 0.1))

    # --- sources ----------------------------------------------------------
    net.add_ext_grid("GRID", bus="SUB_01", vm_pu=1.0)
    net.add_gen("PV", bus="PV_01", p_mw=0.03, vm_pu=1.0)
    # battery inverter as a PQ (static) generator: PV buses in LV feeders with
    # high R/X cables are a known NR convergence hazard
    net.add_sgen("BESS", bus="BESS_01", p_mw=0.01)

    # --- lines ------------------------------------------------------------
    net.add_line(
        "L_SUB_PV", from_bus="SUB_01", to_bus="PV_01", length_km=0.05, std_type="NAYY 4x50 SE"
    )
    net.add_line(
        "L_PV_BESS",
        from_bus="PV_01",
        to_bus="BESS_01",
        length_km=0.15,
        r_ohm_per_km=0.64,
        x_ohm_per_km=0.08,
        c_nf_per_km=210.0,
        max_i_ka=0.142,
    )
    net.add_line(
        "L_BESS_LOAD", from_bus="BESS_01", to_bus="LOAD_01", length_km=0.05, std_type="NAYY 4x50 SE"
    )

    # --- loads ------------------------------------------------------------
    net.add_load("LOAD", bus="LOAD_01", p_mw=0.035, q_mvar=0.005)

    print(f"std types available: {len(net.available_std_types())}")
    print(f"buses: {sorted(net.buses['name'].tolist())}")

    # --- power flow (pandapower backend) ---------------------------------
    res = net.runpp()
    print(f"\nrunpp -> converged={res.converged} solver={res.solver} "
          f"iterations={res.iterations} ({res.elapsed_s * 1e3:.1f} ms)")
    print(net.net.res_bus[["vm_pu", "va_degree"]].round(4).to_string())
    print(net.net.res_line[["loading_percent"]].round(1).to_string())

    # --- power flow (grid2op backend, hot-synced repeated solves) --------
    res2 = net.runpp(backend="grid2op")
    print(f"\ngrid2op backend -> converged={res2.converged} solver={res2.solver}")
    for mw in (0.05, 0.06, 0.07):
        net.net.load.loc[0, "p_mw"] = mw
        res3 = net.runpp(backend="grid2op")
        print(f"  load {mw:4.2f} MW -> converged={res3.converged}, "
              f"V@LOAD_01={net.net.res_bus.loc[3, 'vm_pu']:.4f} pu")

    # --- a non-converging feeder triggers the diagnostic report ----------
    print("\n--- diagnostics demo: kW entered as MW on a 220 V feeder ---")
    bad = gk.create_empty_network()
    bad.add_bus("SUB", vn_kv=0.22)
    for i in range(3):
        bad.add_bus(f"B_{i}", vn_kv=0.22)
    bad.add_ext_grid("GRID", bus="SUB")
    for i in range(3):
        bad.add_line(
            f"L_{i}",
            from_bus="SUB" if i == 0 else f"B_{i - 1}",
            to_bus=f"B_{i}",
            length_km=0.05,
            std_type="NAYY 4x50 SE",
        )
    for i, kw in enumerate((7020, 1350, 1060)):
        bad.add_load(f"LOAD_{i}", bus=f"B_{i}", p_mw=kw)  # kW as MW, ~1000x too big
    bad.runpp(max_iteration=10000)

    # --- plotting (returns figures; call .show() yourself once) ----------
    fig_topo = net.simple_plotly()
    fig_res = net.pf_res_plotly()
    print(f"\nplotly figures ready: simple_plotly({len(fig_topo.data)} traces), "
          f"pf_res_plotly({len(fig_res.data)} traces)")
    print("call net.simple_plotly().show() to display")


if __name__ == "__main__":
    main()
