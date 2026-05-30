from __future__ import annotations

import os
import sys
import threading
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
import plugins.akasha.engine as engine_module
from core.memory.engine import MemoryQuery, MemoryScope
from plugins.akasha.config import AkashaConfig
from plugins.akasha.engine import AkashaMemoryEngine
from plugins.akasha.replay import AkashaReplayRuntime
from plugins.akasha.store import AkashaStore


T0 = 1_700_000_000.0
NOW = T0 + 86_400.0


def _seed_store(path: Path) -> AkashaStore:
    store = AkashaStore(path)
    store.upsert_message_node(
        core.SourceMessage("m0", "s", 0, "user", "alpha", str(T0), 0.0),
        [1.0, 0.0],
    )
    store.upsert_message_node(
        core.SourceMessage("m2", "s", 2, "user", "beta", str(T0), 0.0),
        [0.98, 0.02],
    )
    store.upsert_edges([
        core.EdgeUpdate("s:0", "s:2", 1.0, T0),
        core.EdgeUpdate("s:2", "s:0", 1.0, T0),
    ])
    return store


def _runtime_engine(store: AkashaStore, workspace: Path) -> Any:
    engine = cast(Any, AkashaMemoryEngine.__new__(AkashaMemoryEngine))
    engine._store = store
    engine._session_db_path = workspace / "missing-sessions.db"
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


def _shape(items: list[core.AkashaCandidate]) -> list[tuple[str, str, str]]:
    return [
        (item.key, item.source, item.path_type)
        for item in items
    ]


def _scores(items: list[core.AkashaCandidate]) -> list[float]:
    return [item.score for item in items]


def test_runtime_and_replay_use_same_decayed_edges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_store = _seed_store(tmp_path / "runtime.db")
    replay_store = _seed_store(tmp_path / "replay.db")
    calls = {"runtime": 0, "replay": 0}
    original = core.effective_edge_weight

    try:
        def counted_runtime(weight: float, last_used_ts: float, now_ts: float) -> float:
            calls["runtime"] += 1
            return original(weight, last_used_ts, now_ts)

        monkeypatch.setattr(core, "effective_edge_weight", counted_runtime)
        monkeypatch.setattr(engine_module.time, "time", lambda: NOW)
        engine = _runtime_engine(runtime_store, tmp_path)
        runtime_result = engine._retrieve(
            "alpha",
            np.array([1.0, 0.0], dtype=np.float32),
            MemoryQuery(text="alpha", intent="answer", scope=MemoryScope(session_key="s")),
        )

        def counted_replay(weight: float, last_used_ts: float, now_ts: float) -> float:
            calls["replay"] += 1
            return original(weight, last_used_ts, now_ts)

        monkeypatch.setattr(core, "effective_edge_weight", counted_replay)
        replay = AkashaReplayRuntime(
            store=replay_store,
            config=AkashaConfig(dense_seed_threshold=0.1, nearby_dense_threshold=0.0),
            source_cursor=None,
        )
        replay_items = replay.activate_before_turn(
            core.SourceMessage("m4", "s", 4, "user", "alpha", str(NOW), 0.0),
            [1.0, 0.0],
        )
    finally:
        runtime_store.close()
        replay_store.close()

    assert calls["runtime"] > 0
    assert calls["replay"] > 0
    assert _shape(runtime_result.activation_items) == _shape(replay_items)
    assert _scores(runtime_result.activation_items) == pytest.approx(_scores(replay_items))


def test_store_and_runtime_cache_apply_same_edge_decay(tmp_path: Path) -> None:
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
