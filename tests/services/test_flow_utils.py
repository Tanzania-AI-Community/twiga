from unittest.mock import patch

import pytest
from pydantic import SecretStr

import app.services.flows.utils as flow_utils


def test_decrypt_aes_key_raises_config_error_when_private_key_is_missing() -> None:
    with patch.object(flow_utils.settings, "whatsapp_business_private_key", None):
        with pytest.raises(
            flow_utils.FlowConfigError, match="whatsapp_business_private_key"
        ):
            flow_utils.decrypt_aes_key("unused")


def test_decrypt_aes_key_raises_config_error_when_password_is_blank() -> None:
    with (
        patch.object(
            flow_utils.settings,
            "whatsapp_business_private_key",
            SecretStr("dummy-private-key-for-tests"),
        ),
        patch.object(
            flow_utils.settings,
            "whatsapp_business_private_key_password",
            SecretStr(" "),
        ),
    ):
        with pytest.raises(
            flow_utils.FlowConfigError, match="whatsapp_business_private_key_password"
        ):
            flow_utils.decrypt_aes_key("unused")


def test_get_fernet_key_raises_config_error_when_key_is_blank() -> None:
    with patch.object(
        flow_utils.settings,
        "flow_token_encryption_key",
        SecretStr(" "),
    ):
        with pytest.raises(
            flow_utils.FlowConfigError, match="flow_token_encryption_key"
        ):
            flow_utils.get_fernet_key()
