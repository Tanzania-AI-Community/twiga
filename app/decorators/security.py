from fastapi import Request, HTTPException
import hashlib
import hmac
import logging
from app.config import settings

logger = logging.getLogger(__name__)


def validate_signature(payload: str, signature: str) -> bool:
    """
    Validate the incoming payload's signature against our expected signature
    """
    # Use the App Secret to hash the payload
    expected_signature = hmac.new(
        bytes(settings.meta_app_secret, "latin-1"),
        msg=payload.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()

    # Check if the signature matches
    return hmac.compare_digest(expected_signature, signature)


# Dependency to ensure that incoming requests to our webhook are valid and signed with the correct signature.
async def signature_required(request: Request) -> None:
    """
    Dependency to ensure that incoming requests to our webhook are valid and signed with the correct signature.
    """
    signature = request.headers.get("X-Hub-Signature-256", "")[7:]  # Removing 'sha256='
    payload = await request.body()

    if not validate_signature(payload.decode("utf-8"), signature):
        logger.info("Signature verification failed!")
        raise HTTPException(status_code=403, detail="Invalid signature")


# TODO: rename the folder to something other than decorators