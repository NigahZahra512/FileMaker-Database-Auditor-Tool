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


def _build_graph(data: dict):
    tables = set(data.get("tables", {}).keys())
    edges: dict[str, set] = {}
    for rel in data.get("relationships", []):
        left = rel.get("left_table")
        right = rel.get("right_table")
        if not left or not right:
            continue
        tables.add(left)
        tables.add(right)
        edges.setdefault(left, set()).add(right)
        edges.setdefault(right, set()).add(left)
    return tables, edges


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


def build_erd_summary(data: dict) -> dict:
    tables, edges = _build_graph(data)
    clusters = _connected_clusters(tables, edges)
    orphan_tables = sorted(t for t in tables if not edges.get(t))

    return {
        "stats": {
            "total_tables": len(tables),
            "total_relationships": len(data.get("relationships", [])),
            "cluster_count": len(clusters),
            "orphan_table_count": len(orphan_tables),
        },
        "clusters": [{"tables": c, "size": len(c)} for c in clusters],
        "orphan_tables": orphan_tables,
    }
