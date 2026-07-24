"""
erd_audit.py

ERD Overview
------------
Inspired by the "ERD" tab on the FM Changelog reference tool: total
tables/relationships, how many connected clusters the table graph
splits into, and which tables have zero relationships at all
("orphan tables").

Works entirely off data["relationships"] and data["tables"] -- no
re-parsing, no extra DDR pass.
"""


def _predicate_summary(rel: dict) -> dict:
    """Collapse a relationship's JoinPredicateList into something the
    ERD diagram can label an edge with: the field pairs and whether
    any predicate is a plain Equal join or something looser
    (Cartesian product, Not Equal, etc -- worth flagging visually)."""
    predicates = rel.get("predicates", []) or []
    pairs = []
    all_equal = True
    for p in predicates:
        left_field = (p.get("left_field") or {}).get("name")
        right_field = (p.get("right_field") or {}).get("name")
        ptype = p.get("type") or "Equal"
        if ptype != "Equal":
            all_equal = False
        if left_field and right_field:
            pairs.append(f"{left_field} {ptype} {right_field}")
    return {"pairs": pairs, "all_equal": all_equal}


def _build_graph(data: dict):
    tables = set(data.get("tables", {}).keys())
    edges: dict[str, set] = {}
    edge_list = []
    for rel in data.get("relationships", []):
        left = rel.get("left_table")
        right = rel.get("right_table")
        if not left or not right:
            continue
        tables.add(left)
        tables.add(right)
        edges.setdefault(left, set()).add(right)
        edges.setdefault(right, set()).add(left)
        summary = _predicate_summary(rel)
        edge_list.append({
            "left": left,
            "right": right,
            "predicate_count": len(rel.get("predicates", []) or []),
            "labels": summary["pairs"],
            "all_equal": summary["all_equal"],
        })
    return tables, edges, edge_list


def _connected_clusters(tables: set, edges: dict) -> list[list[str]]:
    """Group tables into connected components via breadth-first search
    over the (undirected) relationship graph."""
    seen = set()
    clusters = []
    for start in tables:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        cluster = []
        while stack:
            node = stack.pop()
            cluster.append(node)
            for neighbour in edges.get(node, ()):
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        clusters.append(sorted(cluster))
    clusters.sort(key=lambda c: (-len(c), c[0].lower() if c else ""))
    return clusters


def _layout_clusters(clusters: list[list[str]]) -> dict:
    """Deterministic node positions (0..1 normalised) for the diagram:
    each cluster gets its own circle of nodes, clusters tiled left to
    right, wrapping into rows. Pure layout math -- no external graph
    library needed on either side."""
    import math

    positions = {}
    per_row = 4
    cell = 1.0 / per_row
    for idx, cluster in enumerate(clusters):
        col = idx % per_row
        row = idx // per_row
        cx = cell * col + cell / 2
        cy_base = row * cell
        n = len(cluster)
        if n == 1:
            positions[cluster[0]] = {"x": cx, "y": cy_base + cell / 2, "cluster": idx}
            continue
        radius = cell * 0.38
        for i, table in enumerate(cluster):
            angle = (2 * math.pi * i / n) - math.pi / 2
            positions[table] = {
                "x": cx + radius * math.cos(angle),
                "y": cy_base + cell / 2 + radius * math.sin(angle),
                "cluster": idx,
            }
    row_count = (len(clusters) + per_row - 1) // per_row if clusters else 1
    return {"nodes": positions, "height_units": max(row_count, 1) * cell}


def build_erd_summary(data: dict) -> dict:
    tables, edges, edge_list = _build_graph(data)
    clusters = _connected_clusters(tables, edges)
    orphan_tables = sorted(t for t in tables if not edges.get(t))
    layout = _layout_clusters(clusters)

    return {
        "stats": {
            "total_tables": len(tables),
            "total_relationships": len(data.get("relationships", [])),
            "cluster_count": len(clusters),
            "orphan_table_count": len(orphan_tables),
        },
        "clusters": [{"tables": c, "size": len(c)} for c in clusters],
        "orphan_tables": orphan_tables,
        "edges": edge_list,
        "layout": layout,
    }
