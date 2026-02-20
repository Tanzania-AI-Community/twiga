import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import app.database.enums as enums
from app.database.models import Message, User
from app.services.latex_image_service import (
    _escape_text_mode_special_chars,
    _extract_latex_document_body,
    _extract_tectonic_error_context,
    prepare_latex_body,
)
from app.services.messaging_service import MessagingService
from app.services.whatsapp_service import ImageType, WhatsAppClient
from app.config import settings


@pytest.mark.asyncio
async def test_send_image_message_returns_true_on_success(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "mock_whatsapp", False)

    client = WhatsAppClient()
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"fake-image")

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None

    try:
        with (
            patch.object(client, "upload_media", AsyncMock(return_value="media-id")),
            patch.object(client, "delete_media", AsyncMock()) as mock_delete_media,
            patch.object(client.client, "post", AsyncMock(return_value=mock_response)),
            patch("app.services.whatsapp_service.log_httpx_response"),
        ):
            result = await client.send_image_message(
                wa_id="255700000000",
                image_path=str(image_path),
                img_type=ImageType.PNG,
            )

        assert result is True
        mock_delete_media.assert_awaited_once_with("media-id", str(image_path))
    finally:
        await client.client.aclose()


@pytest.mark.asyncio
async def test_send_image_message_returns_false_and_cleans_local_file_on_upload_error(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "mock_whatsapp", False)

    client = WhatsAppClient()
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"fake-image")

    try:
        with (
            patch.object(
                client,
                "upload_media",
                AsyncMock(side_effect=ValueError("Image size exceeds limit")),
            ),
            patch("app.services.whatsapp_service.log_httpx_response"),
        ):
            result = await client.send_image_message(
                wa_id="255700000000",
                image_path=str(image_path),
                img_type=ImageType.PNG,
            )

        assert result is False
        assert not image_path.exists()
    finally:
        await client.client.aclose()


@pytest.mark.asyncio
async def test_send_image_message_returns_false_and_cleans_uploaded_media_on_post_error(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "mock_whatsapp", False)

    client = WhatsAppClient()
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"fake-image")

    request = httpx.Request("POST", "https://example.com")
    response = httpx.Response(400, request=request)
    post_response = MagicMock()
    post_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "bad request", request=request, response=response
    )

    try:
        with (
            patch.object(client, "upload_media", AsyncMock(return_value="media-id")),
            patch.object(client, "delete_media", AsyncMock()) as mock_delete_media,
            patch.object(client.client, "post", AsyncMock(return_value=post_response)),
            patch("app.services.whatsapp_service.log_httpx_response"),
        ):
            result = await client.send_image_message(
                wa_id="255700000000",
                image_path=str(image_path),
                img_type=ImageType.PNG,
            )

        assert result is False
        mock_delete_media.assert_awaited_once_with("media-id", str(image_path))
    finally:
        await client.client.aclose()


@pytest.mark.asyncio
async def test_handle_chat_message_falls_back_to_text_when_image_send_fails() -> None:
    service = MessagingService()
    user = User(id=1, wa_id="255700000000", name="Teacher")
    user_message = Message(
        user_id=1,
        role=enums.MessageRole.user,
        content="Solve this: \\frac{1}{2}",
    )
    llm_message = Message(
        user_id=1,
        role=enums.MessageRole.assistant,
        content="\\frac{1}{2}",
    )

    with (
        patch("app.services.messaging_service.llm_settings.agentic_mode", False),
        patch(
            "app.services.messaging_service.llm_client.generate_response",
            AsyncMock(return_value=[llm_message]),
        ),
        patch("app.services.messaging_service.db.create_new_messages", AsyncMock()),
        patch(
            "app.services.messaging_service.text_to_img",
            return_value="/tmp/twiga_latex_image.png",
        ),
        patch(
            "app.services.messaging_service.whatsapp_client.send_image_message",
            AsyncMock(return_value=False),
        ) as mock_send_image,
        patch(
            "app.services.messaging_service.whatsapp_client.send_message",
            AsyncMock(),
        ) as mock_send_message,
        patch("app.services.messaging_service.record_messages_generated"),
    ):
        response = await service.handle_chat_message(
            user=user, user_message=user_message
        )

    assert response.status_code == 200
    mock_send_image.assert_awaited_once()
    mock_send_message.assert_awaited_once_with(user.wa_id, llm_message.content)


def test_extract_latex_document_body() -> None:
    content = r"""
\documentclass{article}
\begin{document}
Example with x_1 and x^2
\end{document}
"""
    assert _extract_latex_document_body(content) == "Example with x_1 and x^2"


def test_escape_text_mode_special_chars() -> None:
    escaped = _escape_text_mode_special_chars("Value x_1 and y^2 in text mode")
    assert escaped == r"Value x\_1 and y\^{}2 in text mode"


def test_escape_text_mode_preserves_math_mode() -> None:
    escaped = _escape_text_mode_special_chars(r"Text x_1 and math $y_2 + z^3$")
    assert escaped == r"Text x\_1 and math $y_2 + z^3$"


def test_prepare_latex_body_normalizes_markdown_headings() -> None:
    prepared = prepare_latex_body("## Step 1\nUse $x_1$ and y^2")
    assert prepared == "Step 1\nUse $x_1$ and y\\^{}2"


def test_prepare_latex_body_converts_markdown_emphasis() -> None:
    prepared = prepare_latex_body(
        "1. **Identify Common Factors**\n*Factorization is complete.*"
    )
    assert (
        prepared
        == "1. \\textbf{Identify Common Factors}\n\\emph{Factorization is complete.}"
    )


def test_prepare_latex_body_preserves_math_operators_while_converting_emphasis() -> (
    None
):
    prepared = prepare_latex_body("Use $a*b*c$ and **bold**")
    assert prepared == "Use $a*b*c$ and \\textbf{bold}"


def test_extract_tectonic_error_context_returns_line_snippet() -> None:
    latex_document = "\n".join(
        [
            r"\documentclass{article}",
            r"\begin{document}",
            "Bad text with x_1",
            r"\end{document}",
        ]
    )
    stderr = "error: llm_output_abcd.tex:3: Missing $ inserted"

    context = _extract_tectonic_error_context(latex_document, stderr)

    assert "line 3: Missing $ inserted" in context
    assert "2:\\begin{document}" in context
    assert "3:Bad text with x_1" in context
