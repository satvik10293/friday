"""
core/spatial/scene_graph.py — FRIDAY V3 (M16)
The persistent Scene Graph: FRIDAY's structural model of the environment. Everything is a
node — rooms, furniture, objects — linked by parent/child (containment) and by spatial
relationships (on, beside, near, …). Each node carries a permanent identity and full
provenance so FRIDAY remembers *relationships*, not pixels:

    Office → Desk → Laptop   (laptop is ON the desk, BESIDE the keyboard, INSIDE the office)

In-memory authoritative for speed, with optional write-through to SQLite (per-thread WAL,
the World-Model discipline) so the graph survives restarts. Nodes only; relationship
inference and tracking live in their own modules.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.spatial.scene_graph")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_") or "node"


def new_node_id() -> str:
    return "SN_" + uuid.uuid4().hex[:12]


class NodeStatus:
    ACTIVE = "active"
    LOST = "lost"
    REMOVED = "removed"


@dataclass
class SceneNode:
    node_id: str
    object_class: str
    label: str
    persistent_id: str                                 # stable cross-session identity
    parent: Optional[str] = None
    children: set = field(default_factory=set)
    position: dict = field(default_factory=dict)
    relationships: list = field(default_factory=list)  # [{relation, target, target_label}]
    confidence: float = 1.0
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    room: str = "unknown"
    session: str = ""
    status: str = NodeStatus.ACTIVE
    attributes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["children"] = sorted(self.children)
        return d


class SceneGraph:
    def __init__(self, *, path: Optional[str] = None, persistent: bool = False,
                 session: str = "") -> None:
        self._nodes: dict[str, SceneNode] = {}
        self._by_pid: dict[str, str] = {}              # persistent_id -> node_id
        self._session = session
        self._lock = threading.RLock()
        self._local = threading.local()
        self._persistent = persistent and bool(path)
        self._path = str(path) if path else None
        if self._persistent:
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            self._init_schema()

    # ── persistence ──────────────────────────────────────────────────────────────
    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self._path, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA busy_timeout=5000")
            self._local.conn = c
        return c

    def _init_schema(self) -> None:
        self._conn().executescript(
            """
            CREATE TABLE IF NOT EXISTS scene_nodes (
                node_id TEXT PRIMARY KEY, persistent_id TEXT, object_class TEXT,
                label TEXT, parent TEXT, position TEXT, relationships TEXT,
                confidence REAL, created REAL, updated REAL, last_seen REAL,
                room TEXT, session TEXT, status TEXT, attributes TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_node_pid ON scene_nodes(persistent_id);
            CREATE INDEX IF NOT EXISTS idx_node_room ON scene_nodes(room);
            """)
        self._conn().commit()

    def _write(self, node: SceneNode) -> None:
        if not self._persistent:
            return
        c = self._conn()
        c.execute(
            "INSERT OR REPLACE INTO scene_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (node.node_id, node.persistent_id, node.object_class, node.label, node.parent,
             json.dumps(node.position), json.dumps(node.relationships), node.confidence,
             node.created, node.updated, node.last_seen, node.room, node.session,
             node.status, json.dumps(node.attributes)))
        c.commit()

    def save(self) -> int:
        """Persist every node (used after a bulk change / on shutdown)."""
        with self._lock:
            nodes = list(self._nodes.values())
        for n in nodes:
            self._write(n)
        return len(nodes)

    def load(self) -> int:
        """Rebuild the in-memory graph from SQLite. Returns nodes loaded."""
        if not self._persistent:
            return 0
        rows = self._conn().execute("SELECT * FROM scene_nodes").fetchall()
        with self._lock:
            self._nodes.clear(); self._by_pid.clear()
            for r in rows:
                node = SceneNode(
                    node_id=r["node_id"], object_class=r["object_class"], label=r["label"],
                    persistent_id=r["persistent_id"], parent=r["parent"],
                    position=_loads(r["position"], {}), relationships=_loads(r["relationships"], []),
                    confidence=r["confidence"], created=r["created"], updated=r["updated"],
                    last_seen=r["last_seen"], room=r["room"], session=r["session"],
                    status=r["status"], attributes=_loads(r["attributes"], {}))
                self._nodes[node.node_id] = node
                self._by_pid[node.persistent_id] = node.node_id
            for node in self._nodes.values():          # rebuild children sets
                if node.parent and node.parent in self._nodes:
                    self._nodes[node.parent].children.add(node.node_id)
        return len(rows)

    # ── rooms + objects ──────────────────────────────────────────────────────────
    def ensure_room(self, room: str) -> SceneNode:
        pid = f"room:{_slug(room)}"
        with self._lock:
            existing = self._by_pid.get(pid)
            if existing is not None:
                return self._nodes[existing]
            node = SceneNode(node_id=new_node_id(), object_class="room", label=room,
                             persistent_id=pid, room=room, session=self._session)
            self._nodes[node.node_id] = node
            self._by_pid[pid] = node.node_id
        self._write(node)
        return node

    def upsert_object(self, *, persistent_id: str, object_class: str, label: str,
                      position: dict, room: str, confidence: float, bbox: Optional[dict] = None,
                      session: str = "", attributes: Optional[dict] = None) -> tuple:
        """Create or refresh an object node under its room. Returns (node, created: bool)."""
        now = time.time()
        room_node = self.ensure_room(room)
        with self._lock:
            nid = self._by_pid.get(persistent_id)
            created = nid is None
            if created:
                node = SceneNode(
                    node_id=new_node_id(), object_class=object_class, label=label,
                    persistent_id=persistent_id, parent=room_node.node_id, position=dict(position),
                    confidence=confidence, room=room, session=session or self._session,
                    attributes=dict(attributes or {}))
                self._nodes[node.node_id] = node
                self._by_pid[persistent_id] = node.node_id
                room_node.children.add(node.node_id)
            else:
                node = self._nodes[nid]
                node.position = dict(position)
                node.confidence = max(node.confidence * 0.5, confidence)
                node.label = label or node.label
                node.last_seen = now
                node.updated = now
                node.status = NodeStatus.ACTIVE
                if attributes:
                    node.attributes.update(attributes)
                if node.room != room:                  # moved rooms → reparent
                    self._reparent(node, room_node, room)
            if bbox:
                node.attributes["bbox"] = bbox
        self._write(node)
        return node, created

    def _reparent(self, node: SceneNode, room_node: SceneNode, room: str) -> None:
        old = self._nodes.get(node.parent) if node.parent else None
        if old is not None:
            old.children.discard(node.node_id)
        node.parent = room_node.node_id
        node.room = room
        room_node.children.add(node.node_id)

    # ── relationships ────────────────────────────────────────────────────────────
    def set_relationships(self, node_id: str, relationships: list) -> bool:
        with self._lock:
            node = self._nodes.get(node_id)
            if node is None:
                return False
            changed = node.relationships != relationships
            node.relationships = list(relationships)
            node.updated = time.time()
        if changed:
            self._write(node)
        return changed

    # ── lifecycle ────────────────────────────────────────────────────────────────
    def mark_status(self, node_id: str, status: str) -> Optional[SceneNode]:
        with self._lock:
            node = self._nodes.get(node_id)
            if node is None:
                return None
            node.status = status
            node.updated = time.time()
        self._write(node)
        return node

    def prune(self, *, now: Optional[float] = None, forget_after_s: float = 120.0) -> list:
        """Remove nodes that have been LOST/REMOVED longer than the timeout. Returns the
        removed persistent ids."""
        now = now if now is not None else time.time()
        removed = []
        with self._lock:
            for nid, node in list(self._nodes.items()):
                if node.object_class == "room":
                    continue
                if node.status in (NodeStatus.LOST, NodeStatus.REMOVED) and \
                        now - node.last_seen > forget_after_s:
                    parent = self._nodes.get(node.parent) if node.parent else None
                    if parent is not None:
                        parent.children.discard(nid)
                    self._nodes.pop(nid, None)
                    self._by_pid.pop(node.persistent_id, None)
                    removed.append(node.persistent_id)
        if removed and self._persistent:
            c = self._conn()
            c.executemany("DELETE FROM scene_nodes WHERE persistent_id=?",
                          [(pid,) for pid in removed])
            c.commit()
        return removed

    # ── queries ──────────────────────────────────────────────────────────────────
    def get(self, node_id: str) -> Optional[SceneNode]:
        return self._nodes.get(node_id)

    def by_persistent(self, persistent_id: str) -> Optional[SceneNode]:
        nid = self._by_pid.get(persistent_id)
        return self._nodes.get(nid) if nid else None

    def by_room(self, room: str) -> list:
        with self._lock:
            return [n for n in self._nodes.values()
                    if n.room == room and n.object_class != "room"]

    def by_class(self, object_class: str) -> list:
        with self._lock:
            return [n for n in self._nodes.values() if n.object_class == object_class]

    def find(self, term: str) -> list:
        t = (term or "").lower()
        with self._lock:
            return [n for n in self._nodes.values() if n.object_class != "room"
                    and (t in n.label.lower() or t in n.object_class.lower())]

    def objects(self) -> list:
        with self._lock:
            return [n for n in self._nodes.values() if n.object_class != "room"]

    def rooms(self) -> list:
        with self._lock:
            return [n for n in self._nodes.values() if n.object_class == "room"]

    def snapshot(self) -> dict:
        with self._lock:
            nodes = [n.to_dict() for n in self._nodes.values()]
        return {"session": self._session, "node_count": len(nodes),
                "rooms": [n for n in nodes if n["object_class"] == "room"],
                "objects": [n for n in nodes if n["object_class"] != "room"]}

    def counts(self) -> dict:
        with self._lock:
            objs = [n for n in self._nodes.values() if n.object_class != "room"]
            return {"nodes": len(self._nodes), "rooms": sum(1 for n in self._nodes.values()
                    if n.object_class == "room"), "objects": len(objs),
                    "active": sum(1 for n in objs if n.status == NodeStatus.ACTIVE)}

    def health(self) -> dict:
        return {"status": "ok", "persistent": self._persistent, **self.counts()}

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


def _loads(text, default):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default
