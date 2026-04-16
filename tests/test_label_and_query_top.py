import os
import sys
from unittest.mock import MagicMock

# Ensure the project root is importable when running tests directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import expenses_automation.main as main


def test_query_string_uses_target_sender_and_label():
    expected = f"from:{main.TARGET_SENDER} -label:{main.LABEL_NAME}"
    assert expected == f"from:{main.TARGET_SENDER} -label:{main.LABEL_NAME}"


def make_fake_gmail(existing_labels=None):
    # Build a fake Gmail client with users().labels().list().execute() and create()
    existing_labels = existing_labels or []
    labels_list_result = {"labels": existing_labels}

    labels_service = MagicMock()
    labels_service.list.return_value.execute.return_value = labels_list_result

    def create(*args, **kwargs):
        # simulate created label with id
        body = kwargs.get("body") if kwargs.get("body") is not None else (args[0] if args else {})
        created = {"id": "LABEL_123", "name": body.get("name")}
        return MagicMock(execute=lambda: created)

    labels_service.create = create

    users_service = MagicMock()
    users_service.labels = MagicMock(return_value=labels_service)

    gmail = MagicMock()
    gmail.users.return_value = users_service
    return gmail


def test_get_or_create_label_creates_when_missing():
    fake_gmail = make_fake_gmail(existing_labels=[])
    label_id = main.get_or_create_label(fake_gmail, "MyLabel")
    assert label_id == "LABEL_123"


def test_get_or_create_label_returns_existing_id():
    existing = [{"id": "LBL_EXIST", "name": "MyLabel"}]
    fake_gmail = make_fake_gmail(existing_labels=existing)
    label_id = main.get_or_create_label(fake_gmail, "MyLabel")
    assert label_id == "LBL_EXIST"
