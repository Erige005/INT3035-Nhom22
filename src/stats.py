"""Bước 8 — Thống kê mạng và vẽ biểu đồ cho báo cáo (NetworkX + Matplotlib).

Đầu ra: data/graph/stats.json và các hình trong data/graph/figures/
"""
import csv
import json
import random
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402

from common import OUT_DIR, PROC_DIR  # noqa: E402

FIG = OUT_DIR / "figures"
FIG.mkdir(exist_ok=True)
plt.rcParams.update({"font.size": 10, "figure.dpi": 150, "axes.spines.top": False, "axes.spines.right": False})
COLOR = "#2a6fb0"


def bar(counter, title, fname, xlabel="Số lượng"):
    items = counter.most_common()
    labels, vals = [k for k, _ in items][::-1], [v for _, v in items][::-1]
    fig, ax = plt.subplots(figsize=(7, 0.35 * len(items) + 1.2))
    ax.barh(labels, vals, color=COLOR)
    for i, v in enumerate(vals):
        ax.text(v, i, f" {v:,}", va="center", fontsize=8)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    fig.tight_layout()
    fig.savefig(FIG / fname)
    plt.close(fig)


def main():
    nodes = {r["id"]: r for r in csv.DictReader(open(OUT_DIR / "nodes.csv", encoding="utf-8"))}
    edges = list(csv.DictReader(open(OUT_DIR / "edges.csv", encoding="utf-8")))
    G = nx.MultiDiGraph()
    for nid, n in nodes.items():
        G.add_node(nid, **n)
    for e in edges:
        G.add_edge(e["src"], e["dst"], rel=e["rel"], support=int(e["support"]))
    U = nx.Graph(G.to_undirected())

    st = {}
    st["nodes"] = G.number_of_nodes()
    st["edges"] = G.number_of_edges()
    st["relation_types"] = len({e["rel"] for e in edges})
    st["node_types"] = dict(Counter(n["type"] for n in nodes.values()).most_common())
    st["edge_types"] = dict(Counter(e["rel"] for e in edges).most_common())
    st["edges_support_ge2"] = sum(int(e["support"]) >= 2 for e in edges)
    # Đồ thị lõi: nghệ sĩ – nhóm – công ty – nhãn hàng – giải thưởng – sự kiện (không gồm lớp bài hát/album)
    works = {"Song", "Album"}
    core_e = [e for e in edges if nodes[e["src"]]["type"] not in works and nodes[e["dst"]]["type"] not in works]
    core_n = {x for e in core_e for x in (e["src"], e["dst"])}
    st["core_nodes"] = len(core_n)
    st["core_edges"] = len(core_e)
    st["core_node_types"] = dict(Counter(nodes[n]["type"] for n in core_n).most_common())
    st["core_edge_types"] = dict(Counter(e["rel"] for e in core_e).most_common())
    st["work_nodes"] = sum(1 for n in nodes.values() if n["type"] in works)
    st["work_edges"] = len(edges) - len(core_e)
    st["edge_langs"] = dict(Counter(e["langs"] for e in edges).most_common())
    st["edge_sources"] = dict(Counter(s for e in edges for s in e["sources"].split("|")).most_common())
    st["undirected_simple_edges"] = U.number_of_edges()
    st["density"] = nx.density(U)
    degs = [d for _, d in G.degree()]
    st["avg_degree"] = sum(degs) / len(degs)
    st["max_degree"] = max(degs)
    comps = sorted(nx.connected_components(U), key=len, reverse=True)
    st["connected_components"] = len(comps)
    st["largest_component_nodes"] = len(comps[0])
    st["largest_component_ratio"] = len(comps[0]) / U.number_of_nodes()
    st["avg_clustering"] = nx.average_clustering(U)
    st["transitivity"] = nx.transitivity(U)
    lcc = U.subgraph(comps[0])
    random.seed(0)
    sample = random.sample(list(lcc.nodes()), min(300, lcc.number_of_nodes()))
    dists = []
    for s in sample:
        dists.extend(nx.single_source_shortest_path_length(lcc, s).values())
    dists = [d for d in dists if d > 0]
    st["avg_shortest_path_lcc_sampled"] = sum(dists) / len(dists)
    st["diameter_lcc_sampled_lower_bound"] = max(dists)
    deg_c = nx.degree_centrality(U)
    btw = nx.betweenness_centrality(lcc, k=min(500, lcc.number_of_nodes()), seed=0)
    # bản thuần Python (không cần scipy — chưa có bản dựng cho Python 3.15)
    from networkx.algorithms.link_analysis.pagerank_alg import _pagerank_python
    pr = _pagerank_python(nx.DiGraph(G))
    nm = lambda i: f"{nodes[i]['name']} ({nodes[i]['type']})"  # noqa: E731
    st["top_degree"] = [(nm(i), U.degree(i)) for i, _ in sorted(deg_c.items(), key=lambda x: -x[1])[:15]]
    st["top_betweenness"] = [(nm(i), round(v, 4)) for i, v in sorted(btw.items(), key=lambda x: -x[1])[:15]]
    st["top_pagerank"] = [(nm(i), round(v, 4)) for i, v in sorted(pr.items(), key=lambda x: -x[1])[:15]]
    for t in ("Brand", "Company", "Group", "Artist"):
        st[f"top_{t.lower()}_by_degree"] = [(nodes[i]["name"], U.degree(i)) for i in
                                           sorted((i for i in U if nodes[i]["type"] == t),
                                                  key=lambda i: -U.degree(i))[:10]]
    try:
        comms = nx.community.louvain_communities(U, seed=0)
        st["louvain_communities"] = len(comms)
        st["louvain_modularity"] = nx.community.modularity(U, comms)
    except Exception as e:  # noqa: BLE001
        st["louvain_error"] = str(e)
    pre = json.load(open(PROC_DIR / "preprocess_stats.json", encoding="utf-8"))
    st["preprocess"] = pre

    json.dump(st, open(OUT_DIR / "stats.json", "w"), ensure_ascii=False, indent=2)

    # ---- Hình
    bar(Counter(st["node_types"]), "Số nút theo loại thực thể", "node_types.png")
    bar(Counter(st["edge_types"]), "Số cạnh theo loại quan hệ", "edge_types.png")
    bar(Counter(st["edge_sources"]), "Số cạnh có dẫn chứng theo nguồn báo", "edge_sources.png")
    bar(Counter(st["core_edge_types"]), "Đồ thị lõi: số cạnh theo loại quan hệ", "core_edge_types.png")
    dc = Counter(U.degree(n) for n in U)
    fig, ax = plt.subplots(figsize=(6, 4))
    xs = sorted(dc)
    ax.loglog(xs, [dc[x] for x in xs], "o", ms=3, color=COLOR)
    ax.set_xlabel("Bậc k (log)")
    ax.set_ylabel("Số nút có bậc k (log)")
    ax.set_title("Phân bố bậc (thang log–log)")
    fig.tight_layout()
    fig.savefig(FIG / "degree_distribution.png")
    plt.close(fig)
    sup = Counter(min(int(e["support"]), 10) for e in edges)
    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.bar([str(k) if k < 10 else "≥10" for k in sorted(sup)], [sup[k] for k in sorted(sup)], color=COLOR)
    ax.set_xlabel("Số bài báo dẫn chứng (support)")
    ax.set_ylabel("Số cạnh")
    ax.set_title("Phân bố độ hỗ trợ của cạnh")
    fig.tight_layout()
    fig.savefig(FIG / "edge_support.png")
    plt.close(fig)
    # Ảnh đồ thị con: 60 nút bậc cao nhất của đồ thị lõi (bỏ lớp bài hát/album)
    top = [i for i, _ in sorted(U.degree(), key=lambda x: -x[1]) if nodes[i]["type"] not in works][:60]
    H = U.subgraph(top)
    palette = {"Artist": "#2a6fb0", "Group": "#d1495b", "Company": "#edae49", "Brand": "#00798c",
               "Award": "#66a182", "Event": "#8d6a9f", "Song": "#999999", "Album": "#555555"}
    fig, ax = plt.subplots(figsize=(10, 8))
    pos = nx.spring_layout(H, seed=1, k=0.6)
    nx.draw_networkx_edges(H, pos, alpha=0.15, ax=ax)
    nx.draw_networkx_nodes(H, pos, node_color=[palette.get(nodes[n]["type"], "#ccc") for n in H],
                           node_size=[30 + 6 * U.degree(n) ** 0.9 for n in H], alpha=0.9, ax=ax)
    nx.draw_networkx_labels(H, pos, {n: nodes[n]["name"][:18] for n in H}, font_size=6, ax=ax)
    for t, c in palette.items():
        ax.scatter([], [], color=c, label=t)
    ax.legend(loc="lower left", fontsize=7, frameon=False)
    ax.set_axis_off()
    ax.set_title("Đồ thị lõi: 60 nút nghệ sĩ/nhóm/công ty/nhãn hàng/giải/sự kiện có bậc cao nhất")
    fig.tight_layout()
    fig.savefig(FIG / "top60_subgraph.png")
    plt.close(fig)
    print(json.dumps({k: v for k, v in st.items() if not k.startswith("top")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
