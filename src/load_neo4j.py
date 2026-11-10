"""Bước 7 — Nạp đồ thị vào Neo4j và chạy thử thuật toán đồ thị bằng Graph Data Science (GDS).

Mô hình lưu trữ:
  (:Entity:<Type> {id, name, type, wikidata, popularity, mentions})
  -[:<REL> {support, first_date, last_date, langs, sources, evidence_sentences, evidence_urls}]->

Cấu hình kết nối đọc từ file .env (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD).
"""
import csv
import json
from collections import defaultdict

from neo4j import GraphDatabase

from common import OUT_DIR, ROOT, read_jsonl


def env():
    cfg = {}
    for line in open(ROOT / ".env", encoding="utf-8"):
        if "=" in line:
            k, v = line.strip().split("=", 1)
            cfg[k] = v
    return cfg


def chunks(xs, n=2000):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def main():
    cfg = env()
    drv = GraphDatabase.driver(cfg["NEO4J_URI"], auth=(cfg["NEO4J_USER"], cfg["NEO4J_PASSWORD"]))
    nodes = list(csv.DictReader(open(OUT_DIR / "nodes.csv", encoding="utf-8")))
    edges = list(csv.DictReader(open(OUT_DIR / "edges.csv", encoding="utf-8")))
    ev = {(r["src"], r["rel"], r["dst"]): r["evidence"] for r in read_jsonl(OUT_DIR / "edges_evidence.jsonl")}

    with drv.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
        s.run("CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE")
        by_type = defaultdict(list)
        for n in nodes:
            n["popularity"] = int(n["popularity"] or 0)
            n["mentions"] = int(n["mentions"] or 0)
            by_type[n["type"]].append(n)
        for t, rows in by_type.items():
            for c in chunks(rows):
                s.run(f"UNWIND $rows AS r CREATE (n:Entity:{t}) SET n = r", rows=c)
        by_rel = defaultdict(list)
        for e in edges:
            evid = ev.get((e["src"], e["rel"], e["dst"]), [])
            by_rel[e["rel"]].append({
                "src": e["src"], "dst": e["dst"], "support": int(e["support"]),
                "first_date": e["first_date"], "last_date": e["last_date"],
                "coref_only": e.get("coref_only") == "1", "langs": e["langs"].split("|"), "sources": e["sources"].split("|"),
                "evidence_sentences": [x["sentence"] for x in evid],
                "evidence_urls": [x["url"] for x in evid],
            })
        for rel, rows in by_rel.items():
            for c in chunks(rows):
                s.run(f"""UNWIND $rows AS r
                          MATCH (a:Entity {{id: r.src}}), (b:Entity {{id: r.dst}})
                          CREATE (a)-[x:{rel}]->(b)
                          SET x.support = r.support, x.coref_only = r.coref_only, x.first_date = r.first_date, x.last_date = r.last_date,
                              x.langs = r.langs, x.sources = r.sources,
                              x.evidence_sentences = r.evidence_sentences, x.evidence_urls = r.evidence_urls""",
                      rows=c)
        n_nodes = s.run("MATCH (n:Entity) RETURN count(n) AS c").single()["c"]
        n_edges = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        n_types = s.run("MATCH ()-[r]->() RETURN count(DISTINCT type(r)) AS c").single()["c"]
        print(f"Neo4j: {n_nodes} nút, {n_edges} cạnh, {n_types} loại quan hệ")

        # ---- Chạy thử thuật toán GDS: PageRank, Louvain, Degree
        gds = {}
        try:
            s.run("CALL gds.graph.drop('kpop', false)")
            s.run("""CALL gds.graph.project('kpop', 'Entity', {ALL: {type: '*', orientation: 'UNDIRECTED',
                       properties: {support: {property: 'support', defaultValue: 1}}}})""")
            s.run("CALL gds.pageRank.write('kpop', {writeProperty: 'pagerank', relationshipWeightProperty: 'support'})")
            r = s.run("CALL gds.louvain.write('kpop', {writeProperty: 'community'}) "
                      "YIELD communityCount, modularity RETURN communityCount, modularity").single()
            gds["louvain_communities"] = r["communityCount"]
            gds["louvain_modularity"] = r["modularity"]
            s.run("CALL gds.degree.write('kpop', {writeProperty: 'degree'})")
            gds["top_pagerank"] = [dict(x) for x in s.run(
                "MATCH (n:Entity) RETURN n.name AS name, n.type AS type, round(n.pagerank, 3) AS pagerank, "
                "toInteger(n.degree) AS degree ORDER BY n.pagerank DESC LIMIT 20")]
            gds["top_communities"] = [dict(x) for x in s.run(
                "MATCH (n:Entity) WITH n.community AS c, count(*) AS size, collect(n) AS ms "
                "ORDER BY size DESC LIMIT 8 "
                "RETURN c AS community, size, [m IN ms | m.name][..0] + "
                "[x IN apoc.coll.sortNodes(ms, 'pagerank')[..6] | x.name] AS top_members")]
            s.run("CALL gds.graph.drop('kpop', false)")
        except Exception as e:  # noqa: BLE001
            gds["error"] = str(e)
        json.dump({"nodes": n_nodes, "edges": n_edges, "rel_types": n_types, **gds},
                  open(OUT_DIR / "neo4j_gds.json", "w"), ensure_ascii=False, indent=2, default=str)
        print(json.dumps(gds, ensure_ascii=False, indent=2, default=str)[:3000])
    drv.close()


if __name__ == "__main__":
    main()
