#!/usr/bin/env python3
"""Validate corot MMQOS requests against the real table and physical SMI graph.

The preprocessor reads stdin and writes stdout; no temporary file is used.
"""
import argparse
import ast
import hashlib
import json
import operator
from pathlib import Path
import re
import struct
import subprocess

import libfdt

NO_LINK = 0xffffffff
_OPERATORS = {
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
    ast.BitOr: operator.or_,
    ast.BitAnd: operator.and_,
    ast.Add: operator.add,
    ast.Sub: operator.sub,
}


def _integer(expression):
    def evaluate(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            return _OPERATORS[type(node.op)](evaluate(node.left),
                                            evaluate(node.right))
        raise ValueError("Unsupported MMQOS constant: " + ast.dump(node))
    return evaluate(ast.parse(expression.strip(), mode="eval").body)


def load_graph(source):
    source = Path(source).resolve()
    table = source / "drivers/interconnect/mediatek/mmqos-mt6985.c"
    text = table.read_text()
    marker = "static const struct mtk_node_desc node_descs_mt6985[] = {"
    start = text.index(marker)
    body = text[text.index("{", start) + 1:text.index("\n};", start)]
    program = """#include <dt-bindings/interconnect/mtk,mmqos.h>
#include <dt-bindings/memory/mt6985-larb-port.h>
#define MMQOS_NO_LINK 0xffffffff
#define DEFINE_MNODE(_name,_id,_a,_b,_c,_link) { _id, _link },
unsigned int pairs[][2] = {
""" + body + "\n};\n"
    result = subprocess.run(
        ["clang", "-E", "-P", "-nostdinc", "-I" + str(source / "include"),
         "-x", "c", "-"], input=program, text=True, check=True,
        capture_output=True)
    graph = {}
    for match in re.finditer(r"\{([^{}]+)\}", result.stdout):
        first, second = match.group(1).split(",")
        node, link = _integer(first), _integer(second)
        if node in graph:
            raise ValueError(f"Duplicate MMQOS node {node:#x}")
        graph[node] = link
    if not graph:
        raise ValueError("Empty MT6985 MMQOS graph")
    for node in graph:
        _chain(graph, node)
    inputs = [
        table, source / "include/dt-bindings/interconnect/mtk,mmqos.h",
        source / "include/dt-bindings/memory/mt6985-larb-port.h",
        source / "include/dt-bindings/memory/mtk-memory-port.h",
        source / "drivers/memory/mtk-smi-downstream.c",
    ]
    hashes = {str(path.relative_to(source)):
              hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    return graph, hashes


def _chain(graph, node):
    chain = []
    while True:
        if node in chain:
            raise ValueError(f"Cycle in MMQOS graph at {node:#x}")
        if node not in graph:
            raise ValueError(f"Missing MMQOS graph node {node:#x}")
        chain.append(node)
        link = graph[node]
        if link == NO_LINK:
            return chain
        node = link


def _property(tree, node, name):
    try:
        return bytes(tree.getprop(node, name))
    except libfdt.FdtException as error:
        if error.err != -libfdt.NOTFOUND:
            raise
        return None


def _strings(tree, node, name):
    value = _property(tree, node, name)
    return [] if value is None else value.rstrip(b"\0").decode().split("\0")


def _cells(value):
    if len(value) % 4:
        raise ValueError("DT property has incomplete cells")
    return list(struct.unpack(">" + "I" * (len(value) // 4), value))


def _nodes(tree, parent=0):
    status = _property(tree, parent, "status")
    if status not in (None, b"okay\0", b"ok\0"):
        return
    yield parent
    node = tree.first_subnode(parent, quiet=(libfdt.NOTFOUND,))
    while node >= 0:
        yield from _nodes(tree, node)
        node = tree.next_subnode(node, quiet=(libfdt.NOTFOUND,))


def _physical_common(tree, active, source_id):
    kind = source_id >> 16
    if kind == 4:
        larb = ((source_id & 0xffff) >> 5) & 0x3f
    elif kind == 3:
        larb = source_id & 0xffff
    else:
        raise ValueError(f"No physical LARB proof for source {source_id:#x}")
    matches = [
        node for node in active
        if "mediatek,mt6985-smi-larb" in _strings(tree, node, "compatible")
        and _property(tree, node, "mediatek,larb-id") ==
        struct.pack(">I", larb)
    ]
    if len(matches) != 1:
        raise ValueError(f"LARB {larb} has {len(matches)} physical DT matches")
    node = matches[0]
    seen = set()
    paths = []
    while True:
        if node in seen:
            raise ValueError("Cycle in physical SMI graph")
        seen.add(node)
        paths.append(tree.get_path(node))
        # The SMI driver identifies the primary common by this flag;
        # subcommons share the same OF compatible but have different IDs.
        if _property(tree, node, "smi-common") is not None:
            value = _property(tree, node, "mediatek,common-id")
            if value is None or len(value) != 4:
                raise ValueError("SMI common has no unambiguous common-id")
            common = struct.unpack(">I", value)[0]
            if common not in (0, 1):
                raise ValueError(f"Unexpected physical SMI common {common}")
            return common, paths
        parents = _property(tree, node, "mediatek,smi")
        if parents is None or not parents:
            raise ValueError("SMI LARB/subcommon parent is missing")
        # mtk-smi-downstream.c's "find smi common dev for mmqos" follows
        # mediatek,smi index 0. Extra parents are the parallel SRAM/power
        # path, not the normal MMQOS bandwidth route.
        node = tree.node_offset_by_phandle(_cells(parents)[0])
        if node not in active:
            raise ValueError("SMI route contains an unavailable supplier")


def _specifiers(tree, value):
    cells = _cells(value)
    specs = []
    index = 0
    while index < len(cells):
        phandle_index = index
        provider = tree.node_offset_by_phandle(cells[index])
        index += 1
        count = _property(tree, provider, "#mtk-interconnect-cells")
        if count is None:
            count = _property(tree, provider, "#interconnect-cells")
        if count is None or len(count) != 4:
            raise ValueError("Interconnect provider has no cell count")
        size = struct.unpack(">I", count)[0]
        if index + size > len(cells):
            raise ValueError("Incomplete interconnect specifier")
        specs.append((cells[phandle_index], cells[index:index + size], index))
        index += size
    if len(specs) % 2:
        raise ValueError("Unpaired interconnect endpoints")
    return cells, specs


def normalize_mmqos_paths(tree, source, normalize=True):
    graph, hashes = load_graph(source)
    active = set(_nodes(tree))
    providers = [
        node for node in active
        if "mediatek,mt6985-mmqos" in _strings(tree, node, "compatible")
    ]
    if len(providers) != 1:
        raise ValueError("Expected exactly one MT6985 MMQOS provider")
    phandle = tree.getprop(providers[0], "phandle").as_uint32()
    smi_source = (Path(source) / "drivers/memory/mtk-smi-downstream.c").read_text()
    if "larb->smi_common = larb->smi_common_dev[0];" not in smi_source:
        raise ValueError("SMI MMQOS parent selection changed; audit required")
    report = {"graph_nodes": len(graph), "source_sha256": hashes,
              "physical_route_basis": "SMI driver follows mediatek,smi index 0 until boolean smi-common",
              "validated_paths": 0, "changes": []}
    for node in sorted(active):
        value = _property(tree, node, "interconnects")
        if value is None:
            continue
        cells, specs = _specifiers(tree, value)
        names = _strings(tree, node, "interconnect-names")
        changed = False
        for index in range(0, len(specs), 2):
            src, dst = specs[index:index + 2]
            if src[0] != phandle or dst[0] != phandle:
                continue
            if len(src[1]) != 1 or len(dst[1]) != 1:
                raise ValueError("MT6985 MMQOS endpoint must have one argument")
            first, last = src[1][0], dst[1][0]
            chain = _chain(graph, first)
            if last not in graph:
                raise ValueError(f"Unknown destination {last:#x}")
            name = names[index // 2] if index // 2 < len(names) else str(index // 2)
            path = tree.get_path(node)
            if last not in chain:
                terminal = chain[-1]
                if (terminal >> 16) != 1 or (last >> 16) != 1:
                    raise ValueError(f"{path}:{name}: no route {first:#x} -> {last:#x}")
                common, smi = _physical_common(tree, active, first)
                if terminal != (0x10000 | common):
                    raise ValueError(f"{path}:{name}: MMQOS/physical SMI common disagree")
                report["changes"].append({
                    "path": path, "name": name,
                    "source": f"{first:#x}", "old_destination": f"{last:#x}",
                    "new_destination": f"{terminal:#x}",
                    "graph_chain": [f"{item:#x}" for item in chain],
                    "physical_common": common, "smi_chain": smi,
                    "smi_parent_index": 0,
                })
                if normalize:
                    cells[dst[2]] = terminal
                    changed = True
            report["validated_paths"] += 1
        if changed:
            tree.setprop(node, "interconnects", struct.pack(">" + "I" * len(cells), *cells))
    report["corrected_paths"] = len(report["changes"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dtb", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=Path("linux-native"))
    args = parser.parse_args()
    tree = libfdt.Fdt(args.dtb.read_bytes())
    print(json.dumps(normalize_mmqos_paths(tree, args.source, False), indent=2))


if __name__ == "__main__":
    main()
