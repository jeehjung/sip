import importlib.util
from pathlib import Path

MODULE = Path(__file__).parents[1] / "backend" / "app.py"
spec = importlib.util.spec_from_file_location("sip_app", MODULE)
appmod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(appmod)


def test_group_suffix_numeric_sort_and_values():
    text = "Part_Name\tMISES\tS11\nCORE_POS_10\t10\t1\nCORE_POS_02\t2\t2\nCORE_POS_01\t1\t3\n"
    headers, rows = appmod.parse_delimited_table(text)
    groups = appmod.group_part_rows(headers, rows)
    assert groups[0]["group_name"] == "CORE_POS"
    assert [p["x"] for p in groups[0]["points"]] == [1, 2, 10]
    assert [p["values_numeric"]["MISES"] for p in groups[0]["points"]] == [1.0, 2.0, 10.0]


def test_no_suffix_is_not_silently_grouped():
    headers, rows = appmod.parse_delimited_table("Part_Name\tMISES\nCORE_POS\t12\n")
    groups = appmod.group_part_rows(headers, rows)
    assert groups[0]["group_name"] == "그룹화 불가 Part"
    assert groups[0]["points"] == []


def test_hbm_gen_static_assignment(tmp_path):
    py_file = tmp_path / "model.py"
    py_file.write_text("HBM_Gen = 'HBM3E'\nOTHER = 12\n", encoding="utf-8")
    assert appmod.extract_hbm_gen([py_file]) == "HBM3E"


def test_hbm_gen_conflicting_assignments_are_unspecified(tmp_path):
    first = tmp_path / "a.py"
    second = tmp_path / "b.py"
    first.write_text('HBM_Gen = "HBM3E"\n', encoding="utf-8")
    second.write_text('HBM_Gen = "HBM4"\n', encoding="utf-8")
    assert appmod.extract_hbm_gen([first, second]) is None


def test_parse_variant_folder_with_por():
    parsed = appmod.parse_variant_folder("SIP_A_HBM3E_12H_POR")
    assert parsed == {
        "product_id": "SIP_A",
        "variant_id": "SIP_A_HBM3E_12H_POR",
        "hbm_gen": "HBM3E",
        "stack": "12H",
        "is_por": True,
    }


def test_parse_variant_folder_without_por_and_underscored_product():
    parsed = appmod.parse_variant_folder("SIP_A_HBM4_8H")
    assert parsed["product_id"] == "SIP_A"
    assert parsed["hbm_gen"] == "HBM4"
    assert parsed["stack"] == "8H"
    assert parsed["is_por"] is False


def test_unrecognized_folder_is_not_a_variant():
    assert appmod.parse_variant_folder("SIP_A_HBM4_8H_backup") is None
