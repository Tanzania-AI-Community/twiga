import base64
import json
import logging
from enum import Enum
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.config import settings

logger = logging.getLogger(__name__)


class FlowRequestAction(str, Enum):
    PING = "ping"
    DATA_EXCHANGE = "data_exchange"
    INIT = "INIT"
    BACK = "BACK"


class FlowConfigError(RuntimeError):
    """Raised when required flow encryption settings are missing or invalid."""


def _read_required_secret(setting_name: str, secret_setting: Any) -> str:
    if secret_setting is None:
        raise FlowConfigError(f"Missing required setting: '{setting_name}'")

    if not hasattr(secret_setting, "get_secret_value"):
        raise FlowConfigError(
            f"Invalid setting type for '{setting_name}': expected secret value"
        )

    secret_value = secret_setting.get_secret_value()
    if not isinstance(secret_value, str) or not secret_value.strip():
        raise FlowConfigError(f"Setting '{setting_name}' must be a non-empty secret")

    return secret_value


def decrypt_aes_key(encrypted_aes_key: str) -> bytes:
    private_key_pem = _read_required_secret(
        "whatsapp_business_private_key", settings.whatsapp_business_private_key
    )
    password = _read_required_secret(
        "whatsapp_business_private_key_password",
        settings.whatsapp_business_private_key_password,
    )

    private_key = serialization.load_pem_private_key(
        private_key_pem.encode(),
        password=password.encode(),
        backend=default_backend(),
    )

    # TODO: Check if this works with flows
    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise ValueError("Private key must be an RSA key")

    decrypted_key = private_key.decrypt(
        base64.b64decode(encrypted_aes_key),
        asym_padding.OAEP(
            mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )

    return decrypted_key


def decrypt_payload(encrypted_data: str, aes_key: bytes, iv: str) -> dict:
    encrypted_data_bytes = base64.b64decode(encrypted_data)
    iv_bytes = base64.b64decode(iv)
    encrypted_data_body = encrypted_data_bytes[:-16]
    encrypted_data_tag = encrypted_data_bytes[-16:]
    decryptor = Cipher(
        algorithms.AES(aes_key),
        modes.GCM(iv_bytes, encrypted_data_tag),
        backend=default_backend(),
    ).decryptor()
    decrypted_data_bytes = decryptor.update(encrypted_data_body) + decryptor.finalize()
    return json.loads(decrypted_data_bytes.decode("utf-8"))


def encrypt_response(response: dict, aes_key: bytes, iv: str) -> str:
    response_bytes = json.dumps(response).encode("utf-8")
    iv_bytes = base64.b64decode(iv)
    inverted_iv_bytes = bytes(~b & 0xFF for b in iv_bytes)
    encryptor = Cipher(
        algorithms.AES(aes_key),
        modes.GCM(inverted_iv_bytes),
        backend=default_backend(),
    ).encryptor()
    encrypted_data = encryptor.update(response_bytes) + encryptor.finalize()
    encrypted_data_tag = encryptor.tag
    encrypted_data_bytes = encrypted_data + encrypted_data_tag
    return base64.b64encode(encrypted_data_bytes).decode("utf-8")


async def decrypt_flow_request(body: dict) -> tuple[dict, bytes, str]:
    try:
        # Validate required fields exist
        required_fields = {"encrypted_flow_data", "encrypted_aes_key", "initial_vector"}
        missing_fields = required_fields - body.keys()
        if missing_fields:
            raise ValueError(f"Missing required fields: {missing_fields}")

        encrypted_flow_data = body["encrypted_flow_data"]
        encrypted_aes_key = body["encrypted_aes_key"]
        initial_vector = body["initial_vector"]

        # Validate field types and content
        if not isinstance(encrypted_flow_data, str):
            raise ValueError("encrypted_flow_data must be a string")
        if not isinstance(encrypted_aes_key, str):
            raise ValueError("encrypted_aes_key must be a string")
        if not isinstance(initial_vector, str):
            raise ValueError("initial_vector must be a string")

        aes_key = decrypt_aes_key(encrypted_aes_key)
        decrypted_payload = decrypt_payload(
            encrypted_flow_data, aes_key, initial_vector
        )

        return decrypted_payload, aes_key, initial_vector
    except ValueError as exc:
        raise ValueError(f"Invalid webhook payload: {str(exc)}")
    except Exception as exc:
        raise RuntimeError(f"Decryption error: {str(exc)}")


def get_fernet_key() -> bytes:
    key = _read_required_secret(
        "flow_token_encryption_key", settings.flow_token_encryption_key
    )
    return key.encode("utf-8")


class FlowTokenError(Exception):
    """Base exception for flow token related errors."""

    pass


def decrypt_flow_token(encrypted_flow_token: str) -> tuple[str, str]:
    """
    Decrypts a flow token and returns token details.

    Args:
        encrypted_flow_token: Encrypted token string
    Returns:
        Tuple of wa_id and flow_id
    """

    try:
        fernet = Fernet(get_fernet_key())
        decrypted_str = fernet.decrypt(encrypted_flow_token.encode("utf-8")).decode(
            "utf-8"
        )

        parts = decrypted_str.split("_")
        if len(parts) != 2:
            raise ValueError("Invalid token format")

        wa_id, flow_id = parts
        return wa_id, flow_id
    except ValueError as exc:
        logger.error(f"Value error during token decryption: {str(exc)}")
        raise FlowTokenError("Invalid token format")
    except Exception as exc:
        logger.error(f"Token decryption failed: {str(exc)}")
        raise FlowTokenError("Token decryption failed")


def encrypt_flow_token(wa_id: str, flow_id: str) -> str:
    key = get_fernet_key()
    fernet = Fernet(key)

    logger.debug(f"Encrypting wa_id: {wa_id} and flow_id: {flow_id}")

    data = f"{wa_id}_{flow_id}".encode("utf-8")
    encrypted_data = fernet.encrypt(data)
    return encrypted_data.decode("utf-8")


def create_flow_response_payload(
    screen: str, data: dict[str, Any], encrypted_flow_token: str | None = None
) -> dict[str, Any]:
    """
    Create standardized flow response payloads
    """
    logger.debug(f"Creating flow response payload with data: {data}")
    if screen == "SUCCESS":
        return {
            "screen": "SUCCESS",
            "data": {
                "extension_message_response": {
                    "params": {
                        "flow_token": encrypted_flow_token,
                    },
                },
            },
        }
    return {
        "screen": screen,
        "data": data,
    }
