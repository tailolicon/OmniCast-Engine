from omnicast.vault import db as vault_db
from omnicast.vault.models import ScriptRecord, ScriptStatus


def test_topic_has_script_product_from_saved_script(tmp_path):
    db_path = tmp_path / "vault.db"
    vault_db.init_db(db_path)
    vault_db.upsert_script(
        ScriptRecord(
            script_id="ch1_run1",
            run_id="run1",
            channel_id="ch1",
            language="en",
            topic="Beat GLP-1 Nausea Naturally",
            score=90,
            approved=True,
            status=ScriptStatus.DRAFT,
            script_content="script",
            cost_usd=0.1,
            created_at="2026-07-03T00:00:00",
            updated_at="2026-07-03T00:00:00",
        ),
        db_path,
    )

    assert vault_db.topic_has_script_product("ch1", "Beat GLP 1 nausea naturally!", db_path) is True
    assert vault_db.topic_has_script_product("ch1", "Different Topic", db_path) is False


def test_mark_topic_used_by_title_creates_manual_topic_guard(tmp_path):
    db_path = tmp_path / "vault.db"
    vault_db.init_db(db_path)

    vault_db.mark_topic_used_by_title(
        "ch1",
        "Manual Product Topic",
        "2026-07-03T00:00:00",
        "product_dir",
        db_path,
    )

    assert vault_db.topic_has_script_product("ch1", "manual product topic", db_path) is True
    topics = vault_db.list_topics("ch1", path=db_path)
    assert len(topics) == 1
    assert topics[0].status.value == "used"
    assert topics[0].used_video_id == "product_dir"
