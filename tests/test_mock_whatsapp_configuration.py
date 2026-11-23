import pytest
from pydantic import ValidationError

from app.config import Environment, Settings


def configuration(**overrides):
    values = {
        "meta_api_version": "v22.0",
        "meta_app_id": "test",
        "meta_app_secret": "test",
        "whatsapp_cloud_number_id": "test",
        "whatsapp_verify_token": "test",
        "whatsapp_api_token": "test",
        "database_url": "postgresql+asyncpg://test:test@127.0.0.1/test",
        "environment": Environment.LOCAL,
        "mock_whatsapp": True,
        "mock_whatsapp_api_url": "http://127.0.0.1:3000/api/whatsapp",
        "mock_whatsapp_token": "test-token",
    }
    return Settings(_env_file=None, **(values | overrides))


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:3000/api/whatsapp",
        "http://localhost:3000/api/whatsapp",
        "http://[::1]:3000/api/whatsapp",
        "http://host.docker.internal:3000/api/whatsapp",
    ],
)
def test_accepts_only_explicit_local_mock_destinations(url):
    assert configuration(mock_whatsapp_api_url=url).mock_whatsapp_api_url == url


@pytest.mark.parametrize(
    "url",
    [
        None,
        "https://graph.facebook.com/v22.0/1",
        "http://example.com",
        "http://localhost@evil.example",
        "http://user:password@localhost",
        "http://localhost?token=secret",
    ],
)
def test_rejects_missing_or_external_mock_destinations(url):
    with pytest.raises(ValidationError):
        configuration(mock_whatsapp_api_url=url)


@pytest.mark.parametrize("environment", [Environment.PRODUCTION, Environment.STAGING])
def test_mock_mode_cannot_run_in_production_or_staging(environment):
    with pytest.raises(ValidationError):
        configuration(environment=environment)


def test_mock_requires_a_separate_local_token():
    with pytest.raises(ValidationError):
        configuration(mock_whatsapp_token=" ")


def test_production_does_not_require_mock_configuration():
    assert not configuration(
        mock_whatsapp=False,
        environment=Environment.PRODUCTION,
        mock_whatsapp_api_url=None,
        mock_whatsapp_token=None,
    ).mock_whatsapp


def test_invalid_mock_configuration_does_not_expose_tokens():
    with pytest.raises(ValidationError) as error:
        configuration(
            mock_whatsapp_api_url="https://example.com",
            mock_whatsapp_token="private-local-token",
            whatsapp_api_token="private-meta-token",
        )
    assert "private-local-token" not in str(error.value)
    assert "private-meta-token" not in str(error.value)
