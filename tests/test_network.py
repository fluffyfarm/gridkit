import warnings

import pytest

warnings.filterwarnings("ignore")

import gridkit as gk


def build_simple_net():
    net = gk.create_empty_network()
    net.add_bus("PV_01", vn_kv=0.4, geo_location=(0, 0))
    net.add_bus("LOAD_01", vn_kv=0.4, geo_location=(1, 0))
    net.add_ext_grid("GRID", bus="PV_01", vm_pu=1.0)
    net.add_line(
        "LINE_01",
        from_bus="PV_01",
        to_bus="LOAD_01",
        length_km=0.1,
        std_type="NAYY 4x50 SE",
    )
    net.add_load("LOAD", bus="LOAD_01", p_mw=0.05, q_mvar=0.01)
    return net


def test_create_and_names():
    net = build_simple_net()
    assert net.bus_index("PV_01") != net.bus_index("LOAD_01")
    assert net.line_index("LINE_01") == 0
    assert net.load_index("LOAD") == 0
    assert net.ext_grid_index("GRID") == 0
    with pytest.raises(KeyError):
        net.bus_index("DOES_NOT_EXIST")
    with pytest.raises(ValueError):
        net.add_bus("PV_01", vn_kv=0.4)  # duplicate name


def test_runpp_pandapower():
    net = build_simple_net()
    res = net.runpp()
    assert res.converged
    assert net.converged is True
    assert net.net.res_bus.vm_pu.notna().all()
    assert (net.net.res_bus.vm_pu <= 1.02).all()
    assert net.net.res_line.loading_percent.notna().all()
    assert res.solver == "pandapower/nr"


def test_runpp_algorithms():
    net = build_simple_net()
    for algo in ("nr", "iwamoto_nr", "gs"):
        res = net.runpp(algorithm=algo)
        assert res.converged, algo


def test_runpp_grid2op_backend():
    net = build_simple_net()
    res = net.runpp(backend="grid2op")
    assert res.converged
    assert "grid2op" in res.solver
    assert net.net.res_bus.vm_pu.notna().all()

    # repeated solve after changing the load (hot-sync path)
    net.net.load.loc[0, "p_mw"] = 0.08
    res2 = net.runpp(backend="grid2op")
    assert res2.converged
    vm_after = net.net.res_bus.vm_pu.iloc[1]
    assert vm_after < 0.98  # more load -> lower voltage


def test_repeated_solves_are_fast():
    import time

    net = build_simple_net()
    net.runpp()
    t0 = time.perf_counter()
    for _ in range(20):
        net.runpp()
    per_solve = (time.perf_counter() - t0) / 20
    assert per_solve < 0.5  # sanity bound, not a benchmark


def test_add_sgen():
    net = gk.create_empty_network()
    net.add_bus("A", vn_kv=0.4)
    net.add_bus("B", vn_kv=0.4)
    net.add_ext_grid("G", bus="A")
    net.add_line("L", from_bus="A", to_bus="B", length_km=0.1, std_type="NAYY 4x50 SE")
    net.add_sgen("PV_INV", bus="B", p_mw=0.02)
    assert net.sgen_index("PV_INV") == 0
    res = net.runpp()
    assert res.converged


def test_to_json_from_json(tmp_path):
    net = build_simple_net()
    path = str(tmp_path / "net.json")
    net.to_json(path)
    loaded = gk.Network.from_json(path)
    assert loaded.bus_index("PV_01") == net.bus_index("PV_01")
    assert len(loaded.net.line) == 1


def test_to_excel_from_excel(tmp_path):
    net = build_simple_net()
    path = str(tmp_path / "net.xlsx")
    net.to_excel(path)
    loaded = gk.from_excel(path)
    assert loaded.bus_index("PV_01") == net.bus_index("PV_01")
    assert loaded.line_index("LINE_01") == 0
    assert loaded.load_index("LOAD") == 0
    assert loaded.ext_grid_index("GRID") == 0
    assert len(loaded.net.line) == 1
    assert loaded.runpp().converged


def test_from_excel_roundtrip_keeps_names(tmp_path):
    net = build_simple_net()
    path = str(tmp_path / "net.xlsx")
    net.to_excel(path)
    loaded = gk.Network.from_excel(path)
    assert set(loaded.buses["name"].tolist()) == {"PV_01", "LOAD_01"}


def test_no_slack_diverges_and_reports():
    net = gk.create_empty_network()
    net.add_bus("A", vn_kv=0.4)
    net.add_bus("B", vn_kv=0.4)
    net.add_line("L", from_bus="A", to_bus="B", length_km=1.0, std_type="NAYY 4x50 SE")
    net.add_load("LOAD", bus="B", p_mw=0.05)
    res = net.runpp()
    assert not res.converged
    assert net.converged is False
