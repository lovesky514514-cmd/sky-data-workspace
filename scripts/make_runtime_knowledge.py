"""Build the runtime search index from checked-in, first-party knowledge cards."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from sky_data_workspace.knowledge import search_terms

ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / "research/knowledge_cards.json"
DATABASE = ROOT / "artifacts/bundle/knowledge.sqlite3"


def build():
    cards = json.loads(CARDS.read_text(encoding="utf-8"))
    runtime_cards = [card for card in cards if card["scope"] == "runtime"]
    if not runtime_cards:
        raise ValueError("No runtime knowledge cards found")
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    pending = DATABASE.with_suffix(".pending")
    with closing(sqlite3.connect(pending)) as database, database:
        database.executescript(
            "DROP TABLE IF EXISTS chunks; DROP TABLE IF EXISTS search_index;"
            "CREATE TABLE chunks (id TEXT PRIMARY KEY, scope TEXT, kind TEXT,"
            " title TEXT, text TEXT, provenance TEXT);"
            "CREATE VIRTUAL TABLE search_index USING fts5(id UNINDEXED, title, body);"
        )
        for card in runtime_cards:
            identifier = "card:" + card["id"]
            title, text = card["title"], card["content"]
            provenance = {
                "sources": card["sources"],
                "review_status": card["review_status"],
                "basis": card.get("basis", "源码/文档观察与项目设计建议"),
            }
            database.execute("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?)", (
                identifier, "runtime", "research_card", title, text,
                json.dumps(provenance, ensure_ascii=False),
            ))
            heading = " ".join(search_terms(" ".join([title, *card["tags"]])))
            database.execute("INSERT INTO search_index VALUES (?, ?, ?)", (
                identifier, heading, " ".join(search_terms(text)),
            ))
        if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Runtime knowledge index failed its integrity check")
    pending.replace(DATABASE)
    print(f"Runtime knowledge: {len(runtime_cards)} cards")


if __name__ == "__main__":
    build()
