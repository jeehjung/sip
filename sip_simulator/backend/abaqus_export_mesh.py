# -*- coding: utf-8 -*-
"""Export boundary mesh and element edges from an Abaqus INP using Abaqus/CAE Python.

Compatible with the older Python runtimes bundled with Abaqus. Invoked as:
abaqus cae noGUI=abaqus_export_mesh.py -- input.inp output.json
"""
from __future__ import print_function
import json
import os
import sys

try:
    from abaqus import *
    from abaqusConstants import *
except Exception as exc:
    raise RuntimeError("This script must run inside Abaqus/CAE Python: %s" % exc)


def arguments():
    if "--" in sys.argv:
        args = sys.argv[sys.argv.index("--") + 1:]
    else:
        args = sys.argv[-2:]
    if len(args) < 2:
        raise RuntimeError("Expected input INP and output JSON paths.")
    return os.path.abspath(args[0]), os.path.abspath(args[1])


def faces_for(element_type, count):
    kind = element_type.upper()
    if kind.startswith("S") or kind.startswith("M3D") or kind.startswith("STRI"):
        if count in (3, 6):
            return [(0, 1, 2)], True
        if count in (4, 8, 9):
            return [(0, 1, 2, 3)], True
    if count in (4, 10) and kind.startswith("C3D"):
        return [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)], False
    if count in (6, 15) and kind.startswith("C3D"):
        return [(0, 2, 1), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)], False
    if count in (8, 20, 27) and kind.startswith("C3D"):
        return [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)], False
    return [], False


def add_triangle(target, a, b, c):
    target.extend([a[0], a[1], a[2], b[0], b[1], b[2], c[0], c[1], c[2]])


def add_face_triangles(target, coords):
    if len(coords) < 3:
        return
    for i in range(1, len(coords) - 1):
        add_triangle(target, coords[0], coords[i], coords[i + 1])


def main():
    inp_path, out_path = arguments()
    # ModelFromInputFile is the Abaqus/CAE model-import API.
    model = mdb.ModelFromInputFile(name="SiPMeshImport", inputFileName=inp_path)
    assembly = model.rootAssembly
    parts = {}
    for instance_name in sorted(assembly.instances.keys()):
        instance = assembly.instances[instance_name]
        part_name = getattr(instance, "partName", None) or instance_name
        if part_name not in parts:
            parts[part_name] = {"name": part_name, "triangles": [], "edges": [], "instances": []}
        output = parts[part_name]
        output["instances"].append(instance_name)
        nodes = {}
        for node in instance.nodes:
            nodes[node.label] = (float(node.coordinates[0]), float(node.coordinates[1]), float(node.coordinates[2]))
        face_map = {}
        edge_map = {}
        shell_faces = []
        for element in instance.elements:
            connectivity = list(element.connectivity)
            local_faces, is_shell = faces_for(str(element.type), len(connectivity))
            if not local_faces:
                continue
            for face in local_faces:
                labels = [connectivity[index] for index in face if index < len(connectivity)]
                if len(labels) < 3 or any(label not in nodes for label in labels):
                    continue
                key = tuple(sorted(labels))
                coords = [nodes[label] for label in labels]
                if is_shell:
                    shell_faces.append(coords)
                else:
                    if key in face_map:
                        face_map[key][0] += 1
                    else:
                        face_map[key] = [1, coords]
                for i in range(len(labels)):
                    a_label = labels[i]
                    b_label = labels[(i + 1) % len(labels)]
                    edge_key = tuple(sorted((a_label, b_label)))
                    if edge_key not in edge_map:
                        edge_map[edge_key] = (nodes[a_label], nodes[b_label])
        for face_data in face_map.values():
            if face_data[0] == 1:
                add_face_triangles(output["triangles"], face_data[1])
        for coords in shell_faces:
            add_face_triangles(output["triangles"], coords)
        for edge in edge_map.values():
            output["edges"].extend([edge[0][0], edge[0][1], edge[0][2],
                                    edge[1][0], edge[1][1], edge[1][2]])
    result = {
        "model_name": os.path.basename(inp_path),
        "parts": [parts[name] for name in sorted(parts.keys())],
        "part_count": len(parts),
        "notes": "Colors are assigned per Part in the web viewer. Unsupported element types may be omitted."
    }
    with open(out_path, "w") as handle:
        json.dump(result, handle, separators=(",", ":"))
    print("Exported %d Parts from %s" % (len(parts), inp_path))


if __name__ == "__main__":
    main()
