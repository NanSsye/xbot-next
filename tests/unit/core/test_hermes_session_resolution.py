import pytest

from xbot.agent.hermes_runtime import _ensure_hermes_import_path, _restore_session_history


@pytest.mark.parametrize("chain", [("child",), ("child", "leaf")])
def test_resolve_resume_session_id_follows_compression_tip(tmp_path, monkeypatch, chain):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _ensure_hermes_import_path()
    from persistence.conversation.lineage import CompressionChild
    from persistence.conversation.messages import NewMessage
    from persistence.conversation.sessions import NewSession
    from persistence_assembly import open_persistence, profile_scope

    with open_persistence(profile_scope(home=tmp_path)) as store:
        store.sessions.create(NewSession(session_id="root", source="xbot"))
        store.messages.append("root", NewMessage(role="user", content="original"))
        parent = "root"
        for child in chain:
            store.lineage.publish_compression_child(
                parent, CompressionChild(session_id=child, source="xbot"),
                [NewMessage(role="assistant", content=child)], require_compression_lease=False,
            )
            parent = child

        resumed, history = _restore_session_history(store, "root")
        assert resumed == chain[-1]
        assert [message["content"] for message in history] == [chain[-1]]
