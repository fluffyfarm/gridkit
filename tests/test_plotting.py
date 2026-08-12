import warnings

warnings.filterwarnings("ignore")

import gridkit as gk


def _net():
    net = gk.create_empty_network()
    net.add_bus("PV_01", vn_kv=0.4, geo_location=(0, 0))
    net.add_bus("LOAD_01", vn_kv=0.4, geo_location=(1, 0))
    net.add_ext_grid("GRID", bus="PV_01")
    net.add_line(
        "LINE_01", from_bus="PV_01", to_bus="LOAD_01", length_km=0.1, std_type="NAYY 4x50 SE"
    )
    net.add_load("LOAD", bus="LOAD_01", p_mw=0.05)
    return net


def test_simple_plotly_returns_figure():
    fig = _net().simple_plotly()
    assert fig is not None
    assert len(fig.data) > 0


def test_pf_res_plotly_requires_convergence():
    import pytest

    net = _net()
    with pytest.raises(RuntimeError):
        net.pf_res_plotly()
    net.runpp()
    fig = net.pf_res_plotly()
    assert len(fig.data) > 0


def test_geodata_autofill_for_missing_buses():
    net = gk.create_empty_network()
    net.add_bus("A", vn_kv=0.4)
    net.add_bus("B", vn_kv=0.4)
    net.add_ext_grid("G", bus="A")
    net.add_line("L", from_bus="A", to_bus="B", length_km=0.1, std_type="NAYY 4x50 SE")
    net.add_load("LOAD", bus="B", p_mw=0.01)
    net.runpp()
    fig = net.simple_plotly()
    assert len(fig.data) > 0
    assert net.net.bus["geo"].notna().all()
