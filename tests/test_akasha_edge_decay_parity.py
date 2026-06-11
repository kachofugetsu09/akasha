from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

HOST_ROOT = Path(os.environ.get("AKASIC_AGENT_ROOT", "/mnt/data/coding/akasic-agent"))
if not HOST_ROOT.exists():
    pytest.skip("akasic-agent host repo is required", allow_module_level=True)
sys.path.append(str(HOST_ROOT))

import plugins.akasha.core as core
from core.memory.engine import MemoryQuery, MemoryScope
from plugins.akasha.config import AkashaConfig
from plugins.akasha.engine import AkashaMemoryEngine, PendingActivation
from plugins.akasha.replay import AkashaReplayRuntime, ReplayMessage, _turn_messages
from plugins.akasha.store import AkashaStore


T0 = 1_700_000_000.0
NOW = T0 + 86_400.0
T0_ISO = datetime.fromtimestamp(T0, timezone.utc).isoformat()
NOW_ISO = datetime.fromtimestamp(NOW, timezone.utc).isoformat()


def _init_sessions_db(path: Path) -> None:
    with closing(sqlite3.connect(str(path))) as db:
        db.execute(
            """
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                session_key TEXT NOT NULL,
                seq INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                ts TEXT NOT NULL
            )
            """
        )
        db.executemany(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("m0", "s", 0, "user", "alpha", T0_ISO),
                ("m2", "s", 2, "user", "beta", T0_ISO),
            ],
        )
        db.execute("CREATE VIRTUAL TABLE messages_fts USING fts5(content)")
        db.execute("INSERT INTO messages_fts(rowid, content) VALUES (1, 'alpha')")
        db.execute("INSERT INTO messages_fts(rowid, content) VALUES (2, 'beta')")
        db.commit()


def _seed_store(path: Path) -> AkashaStore:
    store = AkashaStore(path)
    messages = [
        (core.SourceMessage("m0", "s", 0, "user", "alpha", T0_ISO, 0.0), [1.0, 0.0]),
        (core.SourceMessage("m2", "s", 2, "user", "beta", T0_ISO, 0.0), [0.98, 0.02]),
    ]
    for message, embedding in messages:
        store.upsert_cached_embedding(message=message, model="m", embedding=embedding)
        store.upsert_message_node(message, embedding)
    store.upsert_edges([
        core.EdgeUpdate("s:0", "s:2", 1.0, T0),
        core.EdgeUpdate("s:2", "s:0", 1.0, T0),
    ])
    return store


def _runtime_engine(store: AkashaStore, workspace: Path) -> Any:
    engine = cast(Any, AkashaMemoryEngine.__new__(AkashaMemoryEngine))
    engine._store = store
    engine._session_db_path = workspace / "sessions.db"
    engine._akasha_config = AkashaConfig(dense_seed_threshold=0.1, nearby_dense_threshold=0.0)
    engine._config = SimpleNamespace(
        memory=SimpleNamespace(embedding=SimpleNamespace(model="m"))
    )
    engine._graph_lock = threading.RLock()
    engine._nodes = {}
    engine._edges = {}
    engine._edges_meta = {}
    engine._edges_by_src = {}
    engine._fan = {}
    engine._message_embeddings = {}
    engine._message_turn_keys = {}
    engine._load_graph_cache()
    return engine


def _message_embeddings(store: AkashaStore) -> dict[str, np.ndarray]:
    return dict(store.list_cached_embeddings(model="m"))


def _message_turn_keys() -> dict[str, str]:
    return {"m0": "s:0", "m2": "s:2"}


def _shape(items: list[core.AkashaCandidate]) -> list[tuple[str, str, str]]:
    return [
        (item.key, item.source, item.path_type)
        for item in items
    ]


def _scores(items: list[core.AkashaCandidate]) -> list[float]:
    return [item.score for item in items]


def _node_salience(store: AkashaStore, key: str) -> float:
    node = store.get_node(key)
    assert node is not None
    return node.salience


def _candidate(key: str, score: float) -> core.AkashaCandidate:
    return core.AkashaCandidate(
        key=key,
        source="Dense",
        ripple=0.0,
        direct=score,
        state=0.0,
        edge=0.0,
        long=0.0,
        resource=1.0,
        fan=0,
        score=score,
    )


def test_dense_message_candidates_vectorized_preserves_turn_ranking() -> None:
    nodes = {
        "s:0": core.AkashaNode(
            key="s:0",
            anchor_id="m0",
            session_key="s",
            turn_seq=0,
            first_ts_unix=T0,
            salience=0.0,
            strength=0.0,
            resource=1.0,
            recall_count=0,
            last_activated_ts=0.0,
            last_strength_ts=T0,
            last_resource_ts=T0,
            embedding=np.array([1.0, 0.0], dtype=np.float32),
            emb_count=1,
        ),
        "s:2": core.AkashaNode(
            key="s:2",
            anchor_id="m2",
            session_key="s",
            turn_seq=2,
            first_ts_unix=T0,
            salience=0.0,
            strength=0.0,
            resource=1.0,
            recall_count=0,
            last_activated_ts=0.0,
            last_strength_ts=T0,
            last_resource_ts=T0,
            embedding=np.array([0.0, 1.0], dtype=np.float32),
            emb_count=1,
        ),
        "s:4": core.AkashaNode(
            key="s:4",
            anchor_id="m4",
            session_key="s",
            turn_seq=4,
            first_ts_unix=T0,
            salience=0.0,
            strength=0.0,
            resource=1.0,
            recall_count=0,
            last_activated_ts=0.0,
            last_strength_ts=T0,
            last_resource_ts=T0,
            embedding=np.array([0.0, 0.0], dtype=np.float32),
            emb_count=1,
        ),
    }
    message_embeddings = {
        "m0": np.array([1.0, 0.0], dtype=np.float32),
        "m2": np.array([0.8, 0.6], dtype=np.float32),
        "m3": np.array([0.9, 0.1], dtype=np.float32),
        "bad-dim": np.array([1.0, 0.0, 0.0], dtype=np.float32),
        "m4": np.array([0.0, 0.0], dtype=np.float32),
    }
    message_turn_keys = {
        "m0": "s:0",
        "m2": "s:2",
        "m3": "s:2",
        "bad-dim": "s:0",
        "m4": "s:4",
    }

    loop_result = core.dense_message_candidates(
        np.array([1.0, 0.0], dtype=np.float32),
        nodes,
        message_embeddings,
        message_turn_keys,
        limit=3,
    )
    indexed_result = core.dense_message_candidates(
        np.array([1.0, 0.0], dtype=np.float32),
        nodes,
        message_embeddings,
        message_turn_keys,
        limit=3,
        message_index=core.build_dense_message_index(message_embeddings),
    )

    assert [item.key for item in loop_result] == ["s:0", "s:2", "s:4"]
    assert [item.key for item in indexed_result] == [item.key for item in loop_result]
    assert [item.score for item in loop_result] == pytest.approx([
        1.0,
        0.9 / ((0.9 ** 2 + 0.1 ** 2) ** 0.5),
        0.0,
    ])
    assert [item.score for item in indexed_result] == pytest.approx(
        [item.score for item in loop_result]
    )


def test_parse_ts_unix_rejects_non_iso_timestamp() -> None:
    with pytest.raises(ValueError):
        core.parse_ts_unix(str(T0))


def test_replay_and_runtime_use_same_directional_stdp_edges(tmp_path: Path) -> None:
    candidate = _candidate("s:0", 0.8)
    expected = {
        (item.src_key, item.dst_key): 0.12 * item.strength
        for item in core.activation_edge_updates("s:2", [candidate], T0)
    }

    replay_store = AkashaStore(tmp_path / "replay.db")
    runtime_store = AkashaStore(tmp_path / "runtime.db")
    try:
        with closing(sqlite3.connect(":memory:")) as source_db:
            replay = AkashaReplayRuntime(
                store=replay_store,
                config=AkashaConfig(),
                source_db_path=tmp_path / "sessions.db",
                source_cursor=source_db.cursor(),
                message_embeddings={},
                message_turn_keys={},
            )
            replay.commit_turn(
                [ReplayMessage(core.SourceMessage("m2", "s", 2, "user", "beta", T0_ISO), [1.0, 0.0])],
                [candidate],
            )

        engine = cast(Any, AkashaMemoryEngine.__new__(AkashaMemoryEngine))
        engine._store = runtime_store
        engine._graph_lock = threading.RLock()
        engine._edges = {}
        engine._edges_meta = {}
        engine._edges_by_src = {}
        engine._fan = {}
        engine._commit_pending_activation(
            "s:2",
            PendingActivation(query_id="q", seq=2, ts=T0, items=[candidate]),
        )

        assert replay_store.load_edges() == pytest.approx(expected)
        assert runtime_store.load_edges() == pytest.approx(expected)
        assert expected[("s:0", "s:2")] > expected[("s:2", "s:0")]
    finally:
        replay_store.close()
        runtime_store.close()


def test_runtime_and_replay_use_same_decayed_edges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_sessions_db(tmp_path / "sessions.db")
    runtime_store = _seed_store(tmp_path / "runtime.db")
    replay_store = _seed_store(tmp_path / "replay.db")
    calls = {"runtime": 0, "replay": 0}
    original = core.effective_edge_weight

    try:
        def counted_runtime(weight: float, last_used_ts: float, now_ts: float) -> float:
            calls["runtime"] += 1
            return original(weight, last_used_ts, now_ts)

        monkeypatch.setattr(core, "effective_edge_weight", counted_runtime)
        engine = _runtime_engine(runtime_store, tmp_path)
        runtime_result = engine._retrieve(
            "alpha",
            np.array([1.0, 0.0], dtype=np.float32),
            MemoryQuery(
                text="alpha",
                intent="answer",
                scope=MemoryScope(session_key="s"),
                timestamp=datetime.fromtimestamp(NOW, timezone.utc),
            ),
            now_ts=NOW,
            update_state=True,
        )

        def counted_replay(weight: float, last_used_ts: float, now_ts: float) -> float:
            calls["replay"] += 1
            return original(weight, last_used_ts, now_ts)

        monkeypatch.setattr(core, "effective_edge_weight", counted_replay)
        with closing(sqlite3.connect(str(tmp_path / "sessions.db"))) as source_db:
            replay = AkashaReplayRuntime(
                store=replay_store,
                config=AkashaConfig(dense_seed_threshold=0.1, nearby_dense_threshold=0.0),
                source_db_path=tmp_path / "sessions.db",
                source_cursor=source_db.cursor(),
                message_embeddings=_message_embeddings(replay_store),
                message_turn_keys=_message_turn_keys(),
            )
            replay_items = replay.activate_before_turn(
                core.SourceMessage("m4", "s", 4, "user", "alpha", NOW_ISO, 0.0),
                [1.0, 0.0],
            )
    finally:
        runtime_store.close()
        replay_store.close()

    assert calls["runtime"] > 0
    assert calls["replay"] > 0
    assert _shape(runtime_result.activation_items) == _shape(replay_items)
    assert _scores(runtime_result.activation_items) == pytest.approx(_scores(replay_items))


def test_replay_writes_query_log_with_activation_items(tmp_path: Path) -> None:
    _init_sessions_db(tmp_path / "sessions.db")
    replay_store = _seed_store(tmp_path / "replay.db")
    try:
        with closing(sqlite3.connect(str(tmp_path / "sessions.db"))) as source_db:
            replay = AkashaReplayRuntime(
                store=replay_store,
                config=AkashaConfig(dense_seed_threshold=0.1, nearby_dense_threshold=0.0),
                source_db_path=tmp_path / "sessions.db",
                source_cursor=source_db.cursor(),
                message_embeddings=_message_embeddings(replay_store),
                message_turn_keys=_message_turn_keys(),
            )
            result = replay.replay_turn([
                ReplayMessage(
                    core.SourceMessage("m4", "s", 4, "user", "alpha", NOW_ISO, 0.0),
                    [1.0, 0.0],
                )
            ])

        rows, total = replay_store.list_query_logs(session_key="s", page=1, page_size=10)
        assert total == 1
        raw = replay_store.get_query_log(str(rows[0]["query_id"]))
        assert raw is not None
        activation_items = json.loads(str(raw["activation_items_json"]))
        dense_items = json.loads(str(raw["dense_items_json"]))
        ripple_items = json.loads(str(raw["ripple_items_json"]))
        assert str(rows[0]["query_id"]).startswith("s:4:context:")
        assert rows[0]["intent"] == "context"
        assert rows[0]["activated_count"] == len(result.activation_items)
        assert rows[0]["dense_count"] == len(dense_items)
        assert rows[0]["ripple_count"] == len(ripple_items)
        assert raw["text_block_preview"]
        assert activation_items
        assert dense_items
        assert isinstance(ripple_items, list)
        assert activation_items[0]["user_message"] in {"alpha", "beta"}
    finally:
        replay_store.close()


def test_replay_empty_query_commits_without_activation_or_query_log(tmp_path: Path) -> None:
    _init_sessions_db(tmp_path / "sessions.db")
    replay_store = _seed_store(tmp_path / "replay.db")
    try:
        with closing(sqlite3.connect(str(tmp_path / "sessions.db"))) as source_db:
            replay = AkashaReplayRuntime(
                store=replay_store,
                config=AkashaConfig(dense_seed_threshold=0.1, nearby_dense_threshold=0.0),
                source_db_path=tmp_path / "sessions.db",
                source_cursor=source_db.cursor(),
                message_embeddings=_message_embeddings(replay_store),
                message_turn_keys=_message_turn_keys(),
            )
            result = replay.replay_turn([
                ReplayMessage(
                    core.SourceMessage("m4", "s", 4, "user", "", NOW_ISO, 0.0),
                    [0.0, 0.0],
                )
            ])

        rows, total = replay_store.list_query_logs(session_key="s", page=1, page_size=10)
        assert result.current_key == "s:4"
        assert result.activation_items == []
        assert total == 0
        assert rows == []
        with closing(sqlite3.connect(str(tmp_path / "replay.db"))) as db:
            assert db.execute("SELECT COUNT(*) FROM akasha_activation_events").fetchone()[0] == 0
    finally:
        replay_store.close()


def test_query_log_content_loader_allows_empty_user_message(tmp_path: Path) -> None:
    with closing(sqlite3.connect(str(tmp_path / "sessions.db"))) as db:
        db.execute(
            """
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                session_key TEXT NOT NULL,
                seq INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                ts TEXT NOT NULL
            )
            """
        )
        db.executemany(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("m0", "s", 0, "user", "", T0_ISO),
                ("m1", "s", 1, "assistant", "assistant preview", T0_ISO),
            ],
        )
        db.commit()
        user_message, assistant_preview = _turn_messages(
            db.cursor(),
            "s:0",
            assistant_preview_chars=9,
        )

    assert user_message == ""
    assert assistant_preview == "assistant..."


def test_store_and_runtime_cache_apply_same_edge_decay(tmp_path: Path) -> None:
    _init_sessions_db(tmp_path / "sessions.db")
    store = _seed_store(tmp_path / "akasha.db")
    engine = _runtime_engine(store, tmp_path)
    update = core.EdgeUpdate("s:0", "s:2", 0.5, NOW)

    try:
        store.upsert_edges([update])
        engine._apply_edge_updates([update])
        persisted_edges, persisted_meta = store.load_edges_with_meta()
    finally:
        store.close()

    assert engine._edges[("s:0", "s:2")] == pytest.approx(
        persisted_edges[("s:0", "s:2")]
    )
    assert engine._edges_meta[("s:0", "s:2")] == persisted_meta[("s:0", "s:2")]


def test_store_persists_causal_salience_state(tmp_path: Path) -> None:
    store = AkashaStore(tmp_path / "akasha.db")
    try:
        store.upsert_message_node(
            core.SourceMessage("m10", "s", 10, "user", "first", T0_ISO),
            [1.0, 0.0],
        )
        store.upsert_message_node(
            core.SourceMessage("m12", "s", 12, "user", "second", T0_ISO),
            [0.0, 1.0],
        )
    finally:
        store.close()

    store = AkashaStore(tmp_path / "akasha.db")
    try:
        store.upsert_message_node(
            core.SourceMessage("m14", "s", 14, "user", "third", T0_ISO),
            [1.0, 0.0],
        )
        assert _node_salience(store, "s:10") == pytest.approx(0.0)
        assert _node_salience(store, "s:12") == pytest.approx(1.0)
        assert _node_salience(store, "s:14") == pytest.approx(0.585786, abs=1e-6)
    finally:
        store.close()


def test_replay_and_online_write_same_causal_salience(tmp_path: Path) -> None:
    _init_sessions_db(tmp_path / "sessions.db")
    online_store = AkashaStore(tmp_path / "online.db")
    replay_store = AkashaStore(tmp_path / "replay.db")
    messages = [
        (core.SourceMessage("m10", "s", 10, "user", "first", T0_ISO), [1.0, 0.0]),
        (core.SourceMessage("m12", "s", 12, "user", "second", T0_ISO), [0.0, 1.0]),
        (core.SourceMessage("m14", "s", 14, "user", "third", T0_ISO), [1.0, 0.0]),
    ]
    try:
        for message, embedding in messages:
            online_store.upsert_message_node(message, embedding)
        with closing(sqlite3.connect(str(tmp_path / "sessions.db"))) as source_db:
            replay = AkashaReplayRuntime(
                store=replay_store,
                config=AkashaConfig(),
                source_db_path=tmp_path / "sessions.db",
                source_cursor=source_db.cursor(),
                message_embeddings={},
                message_turn_keys={},
            )
            for message, embedding in messages:
                _ = replay.commit_turn([ReplayMessage(message=message, embedding=embedding)], [])

        assert _node_salience(online_store, "s:10") == pytest.approx(
            _node_salience(replay_store, "s:10")
        )
        assert _node_salience(online_store, "s:12") == pytest.approx(
            _node_salience(replay_store, "s:12")
        )
        assert _node_salience(online_store, "s:14") == pytest.approx(
            _node_salience(replay_store, "s:14")
        )
    finally:
        online_store.close()
        replay_store.close()
