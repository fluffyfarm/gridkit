import warnings

warnings.filterwarnings("ignore")

import pytest

import gridkit as gk


def test_custom_std_type():
    net = gk.create_empty_network()
    net.add_std_type(
        "MY_CABLE",
        dict(
            r_ohm_per_km=0.5,
            x_ohm_per_km=0.1,
            c_nf_per_km=300.0,
            max_i_ka=0.2,
        ),
    )
    assert "MY_CABLE" in net.available_std_types("line")


def test_custom_std_type_missing_param():
    net = gk.create_empty_network()
    with pytest.raises(ValueError):
        net.add_std_type("BAD", dict(r_ohm_per_km=0.5))


def test_load_std_types_from_excel(tmp_path):
    import pandas as pd

    df = pd.DataFrame(
        [
            {
                "name": "NAYY 4x25 MY",
                "r_ohm_per_km": 1.2,
                "x_ohm_per_km": 0.08,
                "c_nf_per_km": 400.0,
                "max_i_ka": 0.125,
            }
        ]
    )
    path = str(tmp_path / "types.xlsx")
    df.to_excel(path, index=False)

    net = gk.create_empty_network()
    imported = net.load_std_types_from_file(path)
    assert imported == ["NAYY 4x25 MY"]
    assert "NAYY 4x25 MY" in net.available_std_types("line")


def test_builtin_nayy_present():
    net = gk.create_empty_network()
    assert "NAYY 4x50 SE" in net.available_std_types("line")
