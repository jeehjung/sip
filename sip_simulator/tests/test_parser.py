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
