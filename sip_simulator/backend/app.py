from __future__ import annotations

import csv
import io
import os
import re
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

ADMIN_MESSAGE = "관리자 (jeeh.jung@samsung.com)에게 문의하세요."
DATA_ROOT = Path(os.environ.get("SIP_DATA_ROOT", "./sample_data")).resolve()
app = FastAPI(title="SiP Simulator API", version="0.2.0")
_MESH_CACHE: dict[tuple[str, int, int], dict[str, Any]] = {}

# TODO: Restrict this to the trusted UI host before an internal production deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


VARIANT_FOLDER_RE = re.compile(r"^(?P<product>.+?)_(?P<hbm>HBM(?:2E|3E|3|4))_(?P<stack>[0-9]+H)(?P<por>_POR)?$")


def parse_variant_folder(folder_name: str) -> dict[str, Any] | None:
    """Parse folders such as SIP_A_HBM3E_12H_POR or SIP_A_HBM4_8H."""
    match = VARIANT_FOLDER_RE.fullmatch(folder_name)
    if not match:
        return None
    return {
        "product_id": match.group("product"),
        "variant_id": folder_name,
        "hbm_gen": match.group("hbm"),
        "stack": match.group("stack"),
        "is_por": bool(match.group("por")),
    }


def find_required_files(variant_dir: Path) -> dict[str, list[Path]]:
    return {
        ext: sorted(
            p for p in variant_dir.iterdir()
            if p.is_file() and p.suffix.lower() == ext
        )
        for ext in (".txt", ".py", ".inp", ".odb")
    }


def is_valid_variant(variant_dir: Path) -> tuple[bool, dict[str, list[Path]]]:
    files = find_required_files(variant_dir)
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


def variant_summary(variant_dir: Path) -> dict[str, Any]:
    parsed = parse_variant_folder(variant_dir.name)
    if not parsed:
        return {}
    valid, files = is_valid_variant(variant_dir)
    py_hbm = extract_hbm_gen(files[".py"]) if files[".py"] else None
    if not valid:
        return {
            **parsed, "available": False, "message": ADMIN_MESSAGE,
            "reason": "선택한 조건 폴더에 필수 확장자(.txt/.py/.inp/.odb) 파일이 모두 있어야 합니다.",
            "files": {ext[1:]: [p.name for p in paths] for ext, paths in files.items()},
            "py_hbm_gen": py_hbm,
        }
    return {
        **parsed, "available": True,
        "folder": str(variant_dir.relative_to(DATA_ROOT)),
        "files": {ext[1:]: [p.name for p in paths] for ext, paths in files.items()},
        "py_hbm_gen": py_hbm,
        "hbm_warning": (f"폴더명 HBM({parsed['hbm_gen']})과 .py HBM_Gen({py_hbm})이 다릅니다."
                       if py_hbm and py_hbm != parsed["hbm_gen"] else None),
    }


def get_variant(variant_id: str) -> tuple[Path, dict[str, list[Path]], dict[str, Any]]:
    if not variant_id or variant_id in {".", ".."} or "/" in variant_id or "\\" in variant_id:
        raise HTTPException(status_code=400, detail="잘못된 variant_id")
    variant_dir = (DATA_ROOT / variant_id).resolve()
    parsed = parse_variant_folder(variant_id)
    if variant_dir.parent != DATA_ROOT or not variant_dir.is_dir() or not parsed:
        raise HTTPException(status_code=404, detail=ADMIN_MESSAGE)
    valid, files = is_valid_variant(variant_dir)
    if not valid:
        raise HTTPException(status_code=409, detail=ADMIN_MESSAGE)
    return variant_dir, files, parsed


@app.get("/api/health")
def health():
    return {"ok": True, "data_root_exists": DATA_ROOT.is_dir()}


@app.get("/api/products")
def products():
    if not DATA_ROOT.is_dir():
        raise HTTPException(status_code=500, detail=f"SIP_DATA_ROOT 경로를 찾을 수 없습니다: {DATA_ROOT}")
    result = []
    for folder in sorted(DATA_ROOT.iterdir()):
        if folder.is_dir() and parse_variant_folder(folder.name):
            result.append(variant_summary(folder))
    return {"products": result, "admin_message": ADMIN_MESSAGE}


@app.get("/api/products/{variant_id}/results")
def product_results(variant_id: str):
    variant_dir, files, parsed = get_variant(variant_id)
    results = []
    for txt in files[".txt"]:
        headers, rows = parse_delimited_table(safe_read_text(txt))
        results.append({
            "file_name": txt.name, "headers": headers,
            "groups": group_part_rows(headers, rows), "row_count": len(rows),
        })
    parameters = []
    for py_file in files[".py"]:
        parameters.append({
            "file_name": py_file.name,
            "parameters": extract_parameter_candidates(safe_read_text(py_file)),
        })
    return {
        **parsed,
        "folder": variant_dir.name,
        "results": results,
        "parameters": parameters,
        "files": {ext[1:]: [p.name for p in paths] for ext, paths in files.items()},
    }


@app.get("/api/products/{variant_id}/parameters")
def product_parameters(variant_id: str):
    variant_dir, files, parsed = get_variant(variant_id)
    output = []
    for py_file in files[".py"]:
        output.append({
            "file_name": py_file.name,
            "parameters": extract_parameter_candidates(safe_read_text(py_file)),
        })
    return {**parsed, "folder": variant_dir.name, "files": output}



@app.get("/api/products/{variant_id}/mesh")
def product_mesh(variant_id: str, file_name: str):
    """Export INP mesh with Abaqus/CAE Python, cached by file modification time."""
    variant_dir, files, parsed = get_variant(variant_id)
    if file_name not in {p.name for p in files[".inp"]}:
        raise HTTPException(status_code=404, detail="선택한 INP 파일을 찾을 수 없습니다.")
    inp_path = (variant_dir / file_name).resolve()
    if inp_path.parent != variant_dir.resolve():
        raise HTTPException(status_code=400, detail="잘못된 INP 파일 경로")
    stat = inp_path.stat()
    cache_key = (str(inp_path), stat.st_mtime_ns, stat.st_size)
    cached = _MESH_CACHE.get(cache_key)
    if cached is not None:
        return cached

    exporter = Path(__file__).with_name("abaqus_export_mesh.py").resolve()
    if not exporter.is_file():
        raise HTTPException(status_code=500, detail="Abaqus mesh exporter 파일이 없습니다.")
    abaqus_command = os.environ.get("ABAQUS_COMMAND", "abaqus").strip()
    timeout = int(os.environ.get("SIP_ABAQUS_TIMEOUT", "300"))
    try:
        with tempfile.TemporaryDirectory(prefix="sip_mesh_") as temp_dir:
            output_path = Path(temp_dir) / "mesh.json"
            args = [abaqus_command, "cae", "noGUI=" + str(exporter), "--", str(inp_path), str(output_path)]
            if os.name == "nt":
                completed = subprocess.run(
                    subprocess.list2cmdline(args), shell=True, cwd=str(variant_dir),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, timeout=timeout,
                )
            else:
                completed = subprocess.run(
                    args, shell=False, cwd=str(variant_dir),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, timeout=timeout,
                )
            if completed.returncode != 0:
                detail = (completed.stdout or "")[-4000:]
                raise RuntimeError("Abaqus mesh export failed. " + detail)
            if not output_path.is_file():
                raise RuntimeError("Abaqus가 mesh.json을 생성하지 않았습니다. " + (completed.stdout or "")[-2000:])
            with output_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail=f"Abaqus mesh export가 {timeout}초 내에 완료되지 않았습니다.")
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Abaqus 모델 변환 실패. ABAQUS_COMMAND와 라이선스/설치 상태를 확인하세요. " + str(exc)[:1500],
        )
    data.update({
        "variant_id": variant_id,
        "file_name": file_name,
        "source": "Abaqus/CAE Python API",
    })
    _MESH_CACHE.clear()
    _MESH_CACHE[cache_key] = data
    return data

@app.get("/api/products/{variant_id}/file-status")
def product_file_status(variant_id: str):
    variant_dir, files, parsed = get_variant(variant_id)
    return {
        **parsed, "folder": variant_dir.name,
        "mesh": {
            "files": [p.name for p in files[".inp"]],
            "status": "파일 확인 완료; 실제 3D mesh 변환/렌더링은 후속 구현 필요",
        },
        "z_deformation": {
            "files": [p.name for p in files[".odb"]], "field": "U3",
            "status": "ODB U3 추출기는 후속 구현 필요",
        },
    }
