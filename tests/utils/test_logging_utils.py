import logging

import httpx
import pytest
from pydantic import SecretStr

from app.config import settings
from app.utils.logging_utils import log_httpx_response

FAKE_TOKEN = "EAAFAKE-token-123"
FAKE_SECRET = "fake-app-secret-456"
PHONE = "255700000001"


@pytest.fixture
def logs(monkeypatch, caplog):
    monkeypatch.setattr(settings, "whatsapp_api_token", SecretStr(FAKE_TOKEN))
    monkeypatch.setattr(settings, "meta_app_secret", SecretStr(FAKE_SECRET))
    caplog.set_level(logging.DEBUG)
    return caplog


def meta_response(status, **body):
    request = httpx.Request(
        "POST",
        f"https://user:pass@graph.facebook.com/v25.0/123/messages?access_token={FAKE_TOKEN}",
        headers={"Authorization": f"Bearer {FAKE_TOKEN}"},
    )
    return httpx.Response(status, request=request, **body)


def assert_no_sensitive_data(text):
    for value in [FAKE_TOKEN, FAKE_SECRET, PHONE, "Bearer", "access_token", "pass@"]:
        assert value not in text


def test_success_logs_url_and_status_without_body(logs):
    log_httpx_response(
        meta_response(
            200,
            json={"contacts": [{"wa_id": PHONE}], "messages": [{"id": "wamid.1"}]},
        )
    )
    assert "Response URL: https://graph.facebook.com/v25.0/123/messages" in logs.text
    assert "200" in logs.text
    assert "wamid.1" not in logs.text
    assert {record.levelno for record in logs.records} == {logging.DEBUG}
    assert_no_sensitive_data(logs.text)


@pytest.mark.parametrize(
    "status, level", [(400, logging.WARNING), (500, logging.ERROR)]
)
def test_errors_keep_safe_meta_diagnostics(logs, status, level):
    error = {
        "message": "(#131030) Recipient phone number not in allowed list",
        "type": "OAuthException",
        "code": 131030,
        "error_subcode": 2494010,
        "error_data": {"details": f"Recipient {PHONE} is not allowed"},
        "fbtrace_id": "AbCdEf123",
    }
    log_httpx_response(meta_response(status, json={"error": error}))
    for value in ["(#131030)", "OAuthException", "131030", "2494010", "AbCdEf123"]:
        assert value in logs.text
    assert {record.levelno for record in logs.records} == {level}
    assert "error_data" not in logs.text
    assert_no_sensitive_data(logs.text)


@pytest.mark.parametrize(
    "body",
    [
        {"content": f"<html>{FAKE_TOKEN} {PHONE}</html>"},
        {"json": [{"message": PHONE}]},
        {"json": {"error": f"token {FAKE_TOKEN}"}},
        {"json": {"detail": PHONE}},
        {"json": {"error": {"error_data": {"phone": PHONE}}}},
    ],
)
def test_unexpected_error_bodies_are_not_logged(logs, body):
    log_httpx_response(meta_response(502, **body))
    assert "Response Error: unavailable" in logs.text
    assert_no_sensitive_data(logs.text)
