from xbot.core.config import load_settings
from xbot.messaging.models import Message, Reply
from xbot.storage.models import Base
from xbot.storage.session import Storage


def test_storage_uses_postgresql_asyncpg():
    settings = load_settings("configs/xbot.toml")
    storage = Storage(settings.storage)
    try:
        assert storage.engine.url.drivername == "postgresql+asyncpg"
    finally:
        import asyncio

        asyncio.run(storage.close())


def test_metadata_contains_initial_tables():
    assert {
        "plugins",
        "skills",
        "agent_events",
        "messages",
        "replies",
        "message_envelopes",
        "dead_letters",
        "conversations",
        "conversation_members",
        "conversation_messages",
        "conversation_states",
        "conversation_summaries",
    }.issubset(Base.metadata.tables.keys())


def test_storage_repository_factories():
    settings = load_settings("configs/xbot.toml")
    storage = Storage(settings.storage)
    try:
        session = storage.session_factory()
        try:
            assert storage.messages(session).__class__.__name__ == "MessageRepository"
            assert storage.conversations(session).__class__.__name__ == "ConversationRepository"
            assert storage.plugins(session).__class__.__name__ == "PluginRepository"
            assert storage.skills(session).__class__.__name__ == "SkillRepository"
            assert storage.agent(session).__class__.__name__ == "AgentRepository"
        finally:
            import asyncio

            asyncio.run(session.close())
    finally:
        import asyncio

        asyncio.run(storage.close())


def test_message_model_builds_default_dedupe_key():
    message = Message(
        platform="web",
        adapter="web",
        conversation_id="test",
        sender_id="tester",
        content="hello",
        raw={"message_id": "abc"},
    )
    from xbot.messaging.models import MessageEnvelope

    assert MessageEnvelope.from_message(message).dedupe_key == "web:web:abc"


def test_reply_record_table_exists():
    table = Base.metadata.tables["replies"]
    assert {"platform", "adapter", "conversation_id", "content"}.issubset(table.columns.keys())


def test_conversation_message_record_can_restore_message_fields():
    table = Base.metadata.tables["conversation_messages"]
    assert {"platform", "adapter", "raw_json"}.issubset(table.columns.keys())


def test_agent_tables_exist():
    assert {
        "agent_tasks",
        "agent_events",
        "agent_background_tasks",
        "agent_scheduled_jobs",
        "agent_artifacts",
    }.issubset(Base.metadata.tables.keys())
