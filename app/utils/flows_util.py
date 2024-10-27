import base64
import json
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from app.config import settings


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
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
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
    flipped_iv = bytearray()
    for byte in base64.b64decode(iv):
        flipped_iv.append(byte ^ 0xFF)

    encryptor = Cipher(
        algorithms.AES(aes_key),
        modes.GCM(bytes(flipped_iv)),
        backend=default_backend(),
    ).encryptor()

    encrypted_response = (
        encryptor.update(json.dumps(response).encode("utf-8"))
        + encryptor.finalize()
        + encryptor.tag
    )

    return base64.b64encode(encrypted_response).decode("utf-8")


def get_flow_payload(wa_id: str, flow: dict) -> str:
    payload = {
        "recipient_type": "individual",
        "messaging_product": "whatsapp",
        "to": wa_id,
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "header": {
                "type": "text",
                "text": flow.get("header", "Flow message header"),
            },
            "body": {"text": flow.get("body", "Flow message body")},
            "footer": {"text": flow.get("footer", "Flow message footer")},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_message_version": flow.get("flow_message_version", "3"),
                    "flow_token": flow.get("flow_token", settings.flow_token),
                    "flow_name": flow.get("flow_name", "default_flow"),
                    "flow_cta": flow.get("flow_cta", "Start"),
                    "flow_action": flow.get("flow_action", "navigate"),
                    "flow_action_payload": flow.get("flow_action_payload", {}),
                },
            },
        },
    }
    return json.dumps(payload)


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
