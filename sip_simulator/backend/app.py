from __future__ import annotations

import csv
import io
import os
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

ADMIN_MESSAGE = "관리자 (jeeh.jung@samsung.com)에게 문의하세요."
DATA_ROOT = Path(os.environ.get("SIP_DATA_ROOT", "./sample_data")).resolve()
app = FastAPI(title="SiP Simulator API", version="0.1.0")

# TODO: Restrict this to the trusted UI host before an internal production deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def exact_por_children(product_dir: Path) -> list[Path]:
    if not product_dir.is_dir():
        return []
    # Exact logical name comparison; POR_old, por and PRE_POR are not candidates.
    return [p for p in product_dir.iterdir() if p.is_dir() and p.name == "POR"]


def find_required_files(por_dir: Path) -> dict[str, list[Path]]:
    return {
        ext: sorted(
            p for p in por_dir.iterdir()
            if p.is_file() and p.suffix.lower() == ext
        )
        for ext in (".txt", ".py", ".inp", ".odb")
    }


def is_valid_por(por_dir: Path) -> tuple[bool, dict[str, list[Path]]]:
    files = find_required_files(por_dir)
    return all(files[ext] for ext in (".txt", ".py", ".inp", ".odb")), files


def parse_delimited_table(text: str) -> tuple[list[str], list[dict[str, str]]]:
    text = text.lstrip("\ufeff")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return [], []
    try:
        dialect = csv.Sniffer().sniff("\n".join(lines[:5]), delimiters="\t,;")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if "\t" in lines[0] else ","
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    if not reader.fieldnames:
        return [], []
    headers = [str(h).strip() for h in reader.fieldnames]
    rows: list[dict[str, str]] = []
    for raw in reader:
        row = {
            str(k).strip(): (v.strip() if isinstance(v, str) else "")
            for k, v in raw.items() if k is not None
        }
        if row:
            rows.append(row)
    return headers, rows


def group_part_rows(headers: list[str], rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    if not headers:
        return []
    part_col = next(
        (h for h in headers if h.strip().lower() in {"part_name", "part name", "partname"}),
        headers[0],
    )
    metrics = [h for h in headers if h != part_col]
    grouped: dict[str, list[dict[str, Any]]] = {}
    ungrouped: list[dict[str, str]] = []
    suffix_re = re.compile(r"^(.*)_([0-9]+)$")

    for row in rows:
        part = row.get(part_col, "").strip()
        match = suffix_re.match(part)
        if not match:
            ungrouped.append({"part_name": part, "reason": "numeric suffix not found"})
            continue
        base, suffix = match.group(1), int(match.group(2))
        values = {metric: row.get(metric, "").strip() for metric in metrics}
        values_numeric: dict[str, float | None] = {}
        for metric, raw in values.items():
            try:
                values_numeric[metric] = float(raw) if raw != "" else None
            except (ValueError, TypeError):
                values_numeric[metric] = None
        grouped.setdefault(base, []).append({
            "x": suffix, "part_name": part, "values": values,
            "values_numeric": values_numeric,
        })

    output: list[dict[str, Any]] = []
    for base, points in sorted(grouped.items()):
        points.sort(key=lambda p: (p["x"], p["part_name"]))
        suffixes = [p["x"] for p in points]
        duplicates = sorted({n for n in suffixes if suffixes.count(n) > 1})
        output.append({
            "group_name": base,
            "metrics": metrics,
            "points": points,
            "warnings": [f"중복 suffix: {duplicates}"] if duplicates else [],
        })
    if ungrouped:
        output.append({
            "group_name": "그룹화 불가 Part",
            "metrics": metrics,
            "points": [],
            "warnings": [f"{len(ungrouped)}개 Part는 마지막 _숫자 패턴이 없어 XY 그룹에서 제외됨"],
            "ungrouped_parts": ungrouped,
        })
    return output


def safe_read_text(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "cp949", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_parameter_candidates(py_text: str) -> list[dict[str, str]]:
    # Static assignment scan only: do not exec/eval simulation scripts.
    result: list[dict[str, str]] = []
    pattern = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*(.*?)\s*(?:#.*)?$")
    for line_no, line in enumerate(py_text.splitlines(), start=1):
        match = pattern.match(line)
        if match and not match.group(1).startswith("__"):
            value = match.group(2).strip()
            if value and len(value) <= 250:
                result.append({"name": match.group(1), "value": value, "line": str(line_no)})
    return result[:500]


def extract_hbm_gen(py_files: list[Path]) -> str | None:
    """Read HBM_Gen from static assignments without executing the .py file."""
    found: list[str] = []
    for py_file in py_files:
        for item in extract_parameter_candidates(safe_read_text(py_file)):
            if item["name"] == "HBM_Gen":
                value = item["value"].strip()
                # Remove surrounding quotes from common string assignments.
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '\"'}:
                    value = value[1:-1].strip()
                if value and value not in found:
                    found.append(value)
    if len(found) == 1:
        return found[0]
    return None


def product_summary(product_dir: Path) -> dict[str, Any]:
    pors = exact_por_children(product_dir)
    if len(pors) != 1:
        return {
            "product_id": product_dir.name, "available": False,
            "message": ADMIN_MESSAGE,
            "reason": "POR 폴더가 없거나 정확한 이름의 POR 폴더가 둘 이상입니다.",
        }
    por = pors[0]
    valid, files = is_valid_por(por)
    if not valid:
        return {
            "product_id": product_dir.name, "available": False,
            "message": ADMIN_MESSAGE,
            "reason": "POR 폴더에 필수 확장자(.txt/.py/.inp/.odb) 파일이 모두 있어야 합니다.",
        }
    hbm_gen = extract_hbm_gen(files[".py"])
    return {
        "product_id": product_dir.name, "available": True,
        "por_id": str(por.relative_to(DATA_ROOT)),
        "hbm_gen": hbm_gen,
        "files": {ext[1:]: [p.name for p in paths] for ext, paths in files.items()},
    }


def get_product_por(product_id: str) -> tuple[Path, dict[str, list[Path]]]:
    if not product_id or product_id in {".", ".."} or "/" in product_id or "\\" in product_id:
        raise HTTPException(status_code=400, detail="잘못된 product_id")
    product_dir = (DATA_ROOT / product_id).resolve()
    if product_dir.parent != DATA_ROOT or not product_dir.is_dir():
        raise HTTPException(status_code=404, detail=ADMIN_MESSAGE)
    pors = exact_por_children(product_dir)
    if len(pors) != 1:
        raise HTTPException(status_code=409, detail=ADMIN_MESSAGE)
    por = pors[0]
    valid, files = is_valid_por(por)
    if not valid:
        raise HTTPException(status_code=409, detail=ADMIN_MESSAGE)
    return por, files


@app.get("/api/health")
def health():
    return {"ok": True, "data_root_exists": DATA_ROOT.is_dir()}


@app.get("/api/products")
def products():
    if not DATA_ROOT.is_dir():
        raise HTTPException(status_code=500, detail=f"SIP_DATA_ROOT 경로를 찾을 수 없습니다: {DATA_ROOT}")
    result = [product_summary(p) for p in sorted(DATA_ROOT.iterdir()) if p.is_dir()]
    return {"products": result, "admin_message": ADMIN_MESSAGE}


@app.get("/api/products/{product_id}/results")
def product_results(product_id: str):
    por, files = get_product_por(product_id)
    results = []
    for txt in files[".txt"]:
        headers, rows = parse_delimited_table(safe_read_text(txt))
        results.append({
            "file_name": txt.name, "headers": headers,
            "groups": group_part_rows(headers, rows), "row_count": len(rows),
        })
    return {
        "product_id": product_id,
        "por_id": str(por.relative_to(DATA_ROOT)),
        "results": results,
        "files": {ext[1:]: [p.name for p in paths] for ext, paths in files.items()},
    }


@app.get("/api/products/{product_id}/parameters")
def product_parameters(product_id: str):
    por, files = get_product_por(product_id)
    output = []
    for py_file in files[".py"]:
        output.append({
            "file_name": py_file.name,
            "parameters": extract_parameter_candidates(safe_read_text(py_file)),
        })
    return {"product_id": product_id, "files": output}


@app.get("/api/products/{product_id}/file-status")
def product_file_status(product_id: str):
    por, files = get_product_por(product_id)
    return {
        "product_id": product_id, "por_id": str(por.relative_to(DATA_ROOT)),
        "mesh": {
            "files": [p.name for p in files[".inp"]],
            "status": "파일 확인 완료; 실제 3D mesh 변환/렌더링은 후속 구현 필요",
        },
        "z_deformation": {
            "files": [p.name for p in files[".odb"]], "field": "U3",
            "status": "ODB U3 추출기는 후속 구현 필요",
        },
    }
