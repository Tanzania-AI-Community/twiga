import base64
import json
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization, padding
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
import logging
from app.config import settings
from cryptography.fernet import Fernet


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
