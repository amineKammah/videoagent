from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from videoagent import api as api_module


def test_list_sessions_includes_title(monkeypatch: pytest.MonkeyPatch):
    fake_sessions = [
        SimpleNamespace(
            id="session-1",
            created_at=datetime(2026, 2, 1, 12, 30, 0),
            title="Q1 Launch Storyboard",
        )
    ]

    import videoagent.db.crud as crud_module

    monkeypatch.setattr(crud_module, "list_sessions", lambda _db, user_id=None: fake_sessions)

    response = api_module.list_sessions(x_user_id="user-1", db=object())

    assert len(response.sessions) == 1
    assert response.sessions[0].session_id == "session-1"
    assert response.sessions[0].title == "Q1 Launch Storyboard"


def test_update_session_title_requires_session_ownership(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        api_module,
        "get_user",
        lambda _db, _user_id: SimpleNamespace(id="user-1", company_id="company-1"),
    )

    import videoagent.db.crud as crud_module

    monkeypatch.setattr(
        crud_module,
        "get_session",
        lambda _db, _session_id: SimpleNamespace(id="session-1", user_id="different-user"),
    )

    with pytest.raises(HTTPException) as exc:
        api_module.update_session_title(
            session_id="session-1",
            request=api_module.SessionTitleUpdateRequest(title="  new title  "),
            x_user_id="user-1",
            db=object(),
        )

    assert exc.value.status_code == 403


def test_update_session_title_updates_and_returns_response(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        api_module,
        "get_user",
        lambda _db, _user_id: SimpleNamespace(id="user-1", company_id="company-1"),
    )

    import videoagent.db.crud as crud_module

    monkeypatch.setattr(
        crud_module,
        "get_session",
        lambda _db, _session_id: SimpleNamespace(id="session-1", user_id="user-1"),
    )
    monkeypatch.setattr(
        crud_module,
        "update_session_title",
        lambda _db, session_id, title, source="manual": SimpleNamespace(
            id=session_id,
            title=title,
            title_source=source,
            title_updated_at=datetime(2026, 2, 1, 10, 15, 0),
        ),
    )
    monkeypatch.setattr(api_module.agent_service.event_store, "append", lambda *args, **kwargs: None)

    response = api_module.update_session_title(
        session_id="session-1",
        request=api_module.SessionTitleUpdateRequest(title="   Product Demo   "),
        x_user_id="user-1",
        db=object(),
    )

    assert response.session_id == "session-1"
    assert response.title == "Product Demo"
    assert response.title_source == "manual"
    assert response.title_updated_at == "2026-02-01T10:15:00"
