from pathlib import Path

from shorts_bot.instagram_webhook import incoming_sender_ids, set_dotenv_value


def test_extracts_customer_igsid_from_instagram_message_webhook() -> None:
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "business-123",
                "messaging": [
                    {
                        "sender": {"id": "customer-456"},
                        "recipient": {"id": "business-123"},
                        "message": {"mid": "message-id", "text": "hello"},
                    }
                ],
            }
        ],
    }

    assert incoming_sender_ids(payload, "business-123") == ["customer-456"]
    assert incoming_sender_ids(payload, "different-business") == []


def test_ignores_message_echoes() -> None:
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "business-123",
                "messaging": [
                    {
                        "sender": {"id": "business-123"},
                        "recipient": {"id": "customer-456"},
                        "message": {"is_echo": True},
                    }
                ],
            }
        ],
    }

    assert incoming_sender_ids(payload, "business-123") == []


def test_updates_dotenv_recipient_without_duplicates(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "SEND_INSTAGRAM_DM=true\nINSTAGRAM_DM_RECIPIENT_ID=old\n"
        "INSTAGRAM_DM_RECIPIENT_ID=duplicate\nOTHER=value\n",
        encoding="utf-8",
    )

    set_dotenv_value(env_path, "INSTAGRAM_DM_RECIPIENT_ID", "customer-456")

    content = env_path.read_text(encoding="utf-8")
    assert content.count("INSTAGRAM_DM_RECIPIENT_ID=") == 1
    assert "INSTAGRAM_DM_RECIPIENT_ID=customer-456" in content
    assert "OTHER=value" in content
