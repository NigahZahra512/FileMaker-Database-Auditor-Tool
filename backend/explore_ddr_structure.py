"""
explore_ddr_structure.py

PURPOSE (Day 1 - Step 0):
Before writing extraction logic, we need to SEE what the real DDR XML
actually looks like. Every FileMaker version exports slightly different
tag names/attributes, so this script scans any DDR file and prints:
  - the tag hierarchy (which tags live under which)
  - how many times each tag appears
  - a sample of the attributes each tag carries

Run this FIRST on the real DDR file (Practice_fmp12.xml) to confirm/adjust
the tag names used in ddr_parser.py.

Usage:
    python explore_ddr_structure.py path/to/file.xml
    python explore_ddr_structure.py path/to/file.xml --max-depth 4
"""

import argparse
import xml.etree.ElementTree as ET
from collections import defaultdict


def strip_ns(tag: str) -> str:
    """Remove XML namespace prefix like {http://...}Tag -> Tag"""
    return tag.split("}")[-1] if "}" in tag else tag


def explore(file_path: str, max_depth: int = 5, sample_limit: int = 2):
    tag_counts = defaultdict(int)
    tag_samples = defaultdict(list)
    tag_paths = set()

    # iterparse = memory-safe streaming parser, critical for 50MB+ DDR files
    context = ET.iterparse(file_path, events=("start",))

    # Track the path (chain of parent tags) as we stream through the file
    path_stack = []

    for event, elem in context:
        tag = strip_ns(elem.tag)
        path_stack.append(tag)
        path = "/".join(path_stack[:max_depth])
        tag_paths.add(path)

        tag_counts[tag] += 1
        if len(tag_samples[tag]) < sample_limit and elem.attrib:
            tag_samples[tag].append(dict(elem.attrib))

        if len(path_stack) > max_depth:
            path_stack.pop()

    print(f"\n=== TAG HIERARCHY (up to depth {max_depth}) ===")
    for p in sorted(tag_paths):
        print(" ", p)

    print(f"\n=== TAG COUNTS ===")
    for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1]):
        print(f"  {tag:30s} x{count}")

    print(f"\n=== SAMPLE ATTRIBUTES (first {sample_limit} per tag) ===")
    for tag, samples in tag_samples.items():
        print(f"  <{tag}>")
        for s in samples:
            print(f"     {s}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Explore a FileMaker DDR XML structure")
    parser.add_argument("file", help="Path to the DDR XML file")
    parser.add_argument("--max-depth", type=int, default=5)
    args = parser.parse_args()

    explore(args.file, max_depth=args.max_depth)
