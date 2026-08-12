import warnings

warnings.filterwarnings("ignore")

import gridkit as gk
from gridkit import diagnostics


def overrated_lv_net():
    """kW numbers entered as MW on a 220 V feeder (the plans.md scenario)."""
    net = gk.create_empty_network()
    net.add_bus("SUB_01", vn_kv=0.22)
    for i in range(4):
        net.add_bus(f"B_{i}", vn_kv=0.22)
    net.add_ext_grid("GRID", bus="SUB_01")
    for i in range(4):
        net.add_line(
            f"L_{i}",
            from_bus="SUB_01" if i == 0 else f"B_{i - 1}",
            to_bus=f"B_{i}",
            length_km=0.05,
            std_type="NAYY 4x50 SE",
        )
    for i, kw in enumerate([7020, 1350, 1060, 468]):
        net.add_load(f"LOAD_{i}", bus=f"B_{i}", p_mw=kw)
    return net


def test_report_flags_units_problem():
    net = overrated_lv_net()
    report = diagnostics.report(net, algorithm="nr", max_iteration=10000)
    assert "did not converge" in report
    assert "Slack (ext_grid) present" in report
    assert "over rated!" in report
    assert "p_mw was filled with MW numbers ~1000x too large" in report
    assert "Most likely cause:" in report


def test_check_slack_ok_and_missing():
    net = gk.create_empty_network()
    net.add_bus("A", vn_kv=0.4)
    missing = diagnostics.check_slack(net)
    assert missing.status == "error"

    net.add_ext_grid("GRID", bus="A")
    ok = diagnostics.check_slack(net)
    assert ok.status == "ok"


def test_check_nan_inf_ignores_unused_optionals():
    net = gk.create_empty_network()
    net.add_bus("A", vn_kv=0.4)
    net.add_bus("B", vn_kv=0.4)
    net.add_line("L", from_bus="A", to_bus="B", length_km=1.0, std_type="NAYY 4x50 SE")
    net.add_load("LOAD", bus="B", p_mw=0.05)  # sn_mva stays NaN -> must not flag
    check = diagnostics.check_nan_inf(net)
    assert check.status == "ok", check.lines


def test_check_line_impedances():
    net = gk.create_empty_network()
    net.add_bus("A", vn_kv=0.4)
    net.add_bus("B", vn_kv=0.4)
    net.add_line(
        "L",
        from_bus="A",
        to_bus="B",
        length_km=1.0,
        r_ohm_per_km=1e-6,  # absurdly low -> flagged
        x_ohm_per_km=0.08,
        c_nf_per_km=210.0,
        max_i_ka=0.142,
    )
    check = diagnostics.check_line_impedances(net)
    assert check.status == "error"
