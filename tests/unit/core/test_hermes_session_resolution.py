from hermes_state import SessionDB


def test_resolve_resume_session_id_follows_latest_compression_leaf(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session("root", source="xbot")
    db.append_message("root", "user", "old root turn")

    db.create_session("older-child", source="xbot", parent_session_id="root")
    db.append_message("older-child", "assistant", "older branch")
    db.create_session("latest-child", source="xbot", parent_session_id="root")
    db.append_message("latest-child", "assistant", "latest branch")

    assert db.resolve_resume_session_id("root") == "latest-child"


def test_resolve_resume_session_id_follows_nested_compression_leaf(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session("root", source="xbot")
    db.append_message("root", "user", "root turn")
    db.create_session("child", source="xbot", parent_session_id="root")
    db.append_message("child", "assistant", "child turn")
    db.create_session("leaf", source="xbot", parent_session_id="child")
    db.append_message("leaf", "assistant", "leaf turn")

    assert db.resolve_resume_session_id("root") == "leaf"
