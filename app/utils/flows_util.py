import base64
import json
from typing import Any, Dict, List, Tuple
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
import logging
from app.database.db import get_user_by_waid
from app.services.whatsapp_service import whatsapp_client

import httpx
from app.config import settings
from cryptography.fernet import Fernet

from app.database.models import User

logger = logging.getLogger(__name__)


def decrypt_aes_key(encrypted_aes_key: str) -> bytes:
    private_key_pem = settings.whatsapp_business_private_key.get_secret_value()
    password = settings.whatsapp_business_private_key_password.get_secret_value()

    private_key = serialization.load_pem_private_key(
        private_key_pem.encode(),
        password=password.encode(),
        backend=default_backend(),
    )

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
    encryptor = Cipher(
        algorithms.AES(aes_key),
        modes.GCM(iv_bytes),
        backend=default_backend(),
    ).encryptor()
    encrypted_data = encryptor.update(response_bytes) + encryptor.finalize()
    encrypted_data_tag = encryptor.tag
    encrypted_data_bytes = encrypted_data + encrypted_data_tag
    return base64.b64encode(encrypted_data_bytes).decode("utf-8")


def decrypt_flow_webhook(body: dict) -> dict:
    encrypted_flow_data = body["encrypted_flow_data"]
    encrypted_aes_key = body["encrypted_aes_key"]
    initial_vector = body["initial_vector"]

    aes_key = decrypt_aes_key(encrypted_aes_key)
    decrypted_payload = decrypt_payload(encrypted_flow_data, aes_key, initial_vector)

    return {
        "decrypted_payload": decrypted_payload,
        "aes_key": aes_key,
        "initial_vector": initial_vector,
    }


def get_fernet_key() -> bytes:
    key = settings.flow_token_encryption_key.get_secret_value()
    if isinstance(key, str):
        key = key.encode("utf-8")
    return key


def decrypt_flow_token(encrypted_flow_token: str) -> tuple:
    key = get_fernet_key()
    fernet = Fernet(key)

    try:
        decrypted_data = fernet.decrypt(encrypted_flow_token.encode("utf-8"))
        # logging.info(f"Decrypted data: {decrypted_data}")
        decrypted_str = decrypted_data.decode("utf-8")
        wa_id, flow_id = decrypted_str.split("_")
        return wa_id, flow_id
    except Exception as e:
        logging.error(f"Decryption failed: {e}")
        raise


def encrypt_flow_token(wa_id: str, flow_id: str) -> str:
    key = get_fernet_key()
    # logging.info(f"Encryption Key: {key}")
    fernet = Fernet(key)

    # log wa_id and flow_id
    logging.info(f"going to encrypt wa_id: {wa_id} and flow_id: {flow_id}")

    data = f"{wa_id}_{flow_id}".encode("utf-8")
    # logging.info(f"Data to encrypt: {data}")
    encrypted_data = fernet.encrypt(data)
    # logging.info(f"Encrypted data: {encrypted_data}")
    return encrypted_data.decode("utf-8")


async def send_whatsapp_flow_message(
    user: User,
    flow_id: str,
    header_text: str,
    body_text: str,
    action_payload: Dict[str, Any],
    flow_cta: str,
) -> None:
    """
    Common utility to send WhatsApp flow messages
    """
    flow_token = encrypt_flow_token(user.wa_id, flow_id)

    payload = {
        "messaging_product": "whatsapp",
        "to": user.wa_id,
        "recipient_type": "individual",
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "header": {
                "type": "text",
                "text": header_text,
            },
            "body": {
                "text": body_text,
            },
            "footer": {
                "text": "Please follow the instructions.",
            },
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_message_version": "3",
                    "flow_action": "navigate",
                    "flow_token": flow_token,
                    "flow_id": flow_id,
                    "flow_cta": flow_cta,
                    "mode": "published",
                    "flow_action_payload": action_payload,
                },
            },
        },
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://graph.facebook.com/{settings.meta_api_version}/{settings.whatsapp_cloud_number_id}/messages",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.whatsapp_api_token.get_secret_value()}",
            },
            json=payload,
        )
        logger.info(f"WhatsApp API response: {response.status_code} - {response.text}")


def create_flow_response_payload(
    screen: str, data: Dict[str, Any], flow_token: str = None
) -> Dict[str, Any]:
    """
    Create standardized flow response payloads
    """
    if screen == "SUCCESS":
        return {
            "screen": "SUCCESS",
            "data": {
                "extension_message_response": {
                    "params": {
                        "flow_token": flow_token,
                    },
                },
            },
        }
    return {
        "screen": screen,
        "data": data,
    }


def handle_token_validation(
    logger: logging.Logger, encrypted_flow_token: str
) -> Tuple[str, str]:
    """
    Validate and decrypt flow token
    Returns (wa_id, flow_id) or raises exception
    """
    if not encrypted_flow_token:
        logger.error("Missing flow token")
        raise ValueError("Missing flow token")

    try:
        wa_id, flow_id = decrypt_flow_token(encrypted_flow_token)
        logger.info(f"Decrypted flow token: {wa_id}, {flow_id}")
        return wa_id, flow_id
    except Exception as e:
        logger.error(f"Error decrypting flow token: {e}")
        raise ValueError("Invalid flow token")


async def validate_user(logger: logging.Logger, wa_id: str) -> User:
    """
    Validate and retrieve user
    """
    user = await get_user_by_waid(wa_id)
    if not user:
        logger.error(f"User data not found for wa_id {wa_id}")
        raise ValueError("User not found")
    return user


def get_flow_text(is_update: bool, update_text: str, new_text: str) -> str:
    """
    Get appropriate flow text based on update state
    """
    return update_text if is_update else new_text


async def handle_error_response(
    wa_id: str, error_message: str, logger: logging.Logger
) -> None:
    """
    Handle error responses consistently
    """
    await whatsapp_client.send_message(wa_id, error_message)
    logger.error(error_message)


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
