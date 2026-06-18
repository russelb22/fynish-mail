from __future__ import annotations

from app.core import config


OWNER_HEADERS = {
    "X-Fynish-Authenticated-Email": "owner@example.com",
    "X-Fynish-Authenticated-Name": "Owner User",
    "X-Fynish-Authenticated-Sub": "owner-subject",
}

FRIEND_HEADERS = {
    "X-Fynish-Authenticated-Email": "friend@example.com",
    "X-Fynish-Authenticated-Name": "Friend User",
    "X-Fynish-Authenticated-Sub": "friend-subject",
}


def test_ai_digest_attention_notes_crud(api_client, isolated_db):
    response = api_client.get("/api/settings/ai-digest-attention-notes")

    assert response.status_code == 200
    assert [note["domain"] for note in response.json()["notes"]] == [
        "example.net",
        "truecoach.co",
    ]

    response = api_client.post(
        "/api/settings/ai-digest-attention-notes",
        json={
            "domain": "Example.COM",
            "label": "Example",
            "note": "Treat routine reports as routine unless the snippet shows escalation.",
        },
    )

    assert response.status_code == 200
    created = response.json()["note"]
    assert created["domain"] == "example.com"

    response = api_client.patch(
        f"/api/settings/ai-digest-attention-notes/{created['id']}",
        json={"enabled": False, "note": "Updated digest-only guidance."},
    )

    assert response.status_code == 200
    assert response.json()["note"]["enabled"] is False
    assert response.json()["note"]["note"] == "Updated digest-only guidance."

    response = api_client.delete(
        f"/api/settings/ai-digest-attention-notes/{created['id']}",
    )

    assert response.status_code == 200
    assert response.json() == {"deleted": True}


def test_ai_digest_attention_notes_are_user_scoped(api_client, isolated_db, monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "cloud")

    response = api_client.post(
        "/api/settings/ai-digest-attention-notes",
        headers=OWNER_HEADERS,
        json={
            "domain": "owner.example.com",
            "label": "Owner",
            "note": "Owner-only guidance.",
        },
    )
    assert response.status_code == 200
    owner_note = response.json()["note"]

    friend_list = api_client.get(
        "/api/settings/ai-digest-attention-notes",
        headers=FRIEND_HEADERS,
    )
    assert friend_list.status_code == 200
    assert "owner.example.com" not in [
        note["domain"] for note in friend_list.json()["notes"]
    ]

    friend_patch = api_client.patch(
        f"/api/settings/ai-digest-attention-notes/{owner_note['id']}",
        headers=FRIEND_HEADERS,
        json={"enabled": False},
    )
    assert friend_patch.status_code == 404


def test_ai_digest_attention_notes_reject_blank_note(api_client, isolated_db):
    response = api_client.post(
        "/api/settings/ai-digest-attention-notes",
        json={"domain": "example.com", "note": "   "},
    )

    assert response.status_code == 400
    assert "note is required" in response.json()["detail"]
