from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from app.main import INTERNAL_ERROR_CODE, unhandled_exception_handler


@pytest.mark.anyio
async def test_unhandled_exception_handler_returns_safe_response(caplog):
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/example",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "scheme": "http",
            "client": ("testclient", 50000),
        }
    )

    response = await unhandled_exception_handler(
        request,
        RuntimeError("database password is secret"),
    )

    assert response.status_code == 500
    assert json.loads(response.body) == {
        "detail": "Request failed.",
        "code": INTERNAL_ERROR_CODE,
    }
    assert "method=POST path=/api/example" in caplog.text
    assert "database password is secret" not in response.body.decode()
