import base64
import json
from typing import Any, Dict, List, Optional, Tuple
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.asymmetric import rsa

import logging

from app.config import settings
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


def decrypt_aes_key(encrypted_aes_key: str) -> bytes:
    assert (
        settings.whatsapp_business_private_key
        and settings.whatsapp_business_private_key_password
    )
    assert (
        settings.whatsapp_business_private_key.get_secret_value().strip()
        and settings.whatsapp_business_private_key_password.get_secret_value().strip()
    )
    private_key_pem = settings.whatsapp_business_private_key.get_secret_value()
    password = settings.whatsapp_business_private_key_password.get_secret_value()

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


async def decrypt_flow_request(body: dict) -> Tuple[dict, bytes, str]:
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
    assert (
        settings.flow_token_encryption_key
        and settings.flow_token_encryption_key.get_secret_value().strip()
    )
    key = settings.flow_token_encryption_key.get_secret_value()
    if isinstance(key, str):
        key = key.encode("utf-8")
    return key


class FlowTokenError(Exception):
    """Base exception for flow token related errors."""

    pass


def decrypt_flow_token(encrypted_flow_token: str) -> Tuple[str, str]:
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
    screen: str, data: Dict[str, Any], encrypted_flow_token: Optional[str] = None
) -> Dict[str, Any]:
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


def create_subject_class_payload(
    subject_title: str, classes: List[dict], is_update: bool, subject_id: str
) -> Dict[str, Any]:
    """
    Create standardized subject/class selection payload
    """
    has_items = len(classes) > 0
    return {
        "classes": (
            classes
            if has_items
            else [
                {"id": "0", "title": "No classes available"}
            ]  # if no classes, show a dummy class it is required for the client
        ),
        "has_classes": has_items,
        "no_classes_text": f"Sorry, currently there are no active classes for {subject_title}.",
        "select_class_text": f"This helps us find the best answers for your questions in {subject_title}.",
        "select_class_question_text": f"Select the class you are in for {subject_title}.",
        "subject_id": str(subject_id),
    }
