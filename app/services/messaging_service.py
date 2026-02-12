import logging
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import uuid
from urllib import request

from fastapi.responses import JSONResponse
import fitz

import app.database.models as models
from app.services.flow_service import flow_client
from app.utils.string_manager import strings, StringCategory
from app.services.whatsapp_service import whatsapp_client, ImageType
import app.database.db as db
from app.services.llm_service import llm_client
from app.services.agent_client import agent_client
from app.config import llm_settings
import app.database.enums as enums
from app.monitoring.metrics import record_messages_generated, track_messages
from app.tools.registry import ToolName


# Tectonic (https://tectonic-typesetting.github.io/) is a fast
# LaTeX engine we invoke to turn the LLM output into a PDF. We bootstrap a
# platform-specific binary at runtime so deployments don't need a heavyweight
# TeX distribution baked in, yet we still get consistent rendering everywhere.
TECTONIC_VERSION = "0.15.0"
TECTONIC_CACHE_ROOT = os.path.join(
    os.path.expanduser("~/.cache"),
    "twiga",
    "tectonic",
)
WHATSAPP_MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024
PDF_RENDER_DPI_CANDIDATES = (300, 250, 200, 150, 120)

LATEX_TRIGGER_RE = re.compile(
    r"(\\begin\{|\\end\{|\\documentclass|\\usepackage|\\frac|\\sum|"
    r"\\int|\\sqrt|\\left|\\right|\\text\{|\\section|\\alpha|\\beta|"
    r"\\gamma|\\pi|\\theta|\\[|\\]|\\(|\\)|\$)"
)
LATEX_DOCUMENT_BODY_RE = re.compile(
    r"\\begin\{document\}(.*?)\\end\{document\}",
    re.DOTALL,
)
TECTONIC_ERROR_LINE_RE = re.compile(r":[^:\n]+:(\d+):\s*(.+)")

LATEX_TEMPLATE = r"""
\documentclass[11pt]{article}
\usepackage{amsmath, amssymb}
\usepackage{geometry}
\usepackage{lmodern}
\usepackage[T1]{fontenc}
\usepackage{microtype}
\geometry{paperwidth=210mm, paperheight=297mm, margin=15mm}
\setlength{\parskip}{0.75em}
\setlength{\parindent}{0pt}
\pagenumbering{gobble}
\begin{document}
__CONTENT__
\end{document}
"""


def _strip_markdown_code_fences(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _extract_latex_document_body(content: str) -> str:
    match = LATEX_DOCUMENT_BODY_RE.search(content)
    if match:
        return match.group(1).strip()
    return content.strip()


def _normalize_markdown_headings(content: str) -> str:
    normalized_lines: list[str] = []
    for line in content.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            normalized_lines.append(re.sub(r"^#+\s*", "", stripped).strip())
            continue
        normalized_lines.append(line)
    return "\n".join(normalized_lines)


def _escape_text_mode_special_chars(content: str) -> str:
    escaped_chars: list[str] = []
    in_inline_math = False
    in_display_math = False
    last_inline_math_index: int | None = None
    last_display_math_index: int | None = None

    i = 0
    while i < len(content):
        if content.startswith(r"\(", i):
            in_inline_math = True
            escaped_chars.append(r"\(")
            i += 2
            continue
        if content.startswith(r"\)", i):
            in_inline_math = False
            escaped_chars.append(r"\)")
            i += 2
            continue
        if content.startswith(r"\[", i):
            in_display_math = True
            escaped_chars.append(r"\[")
            i += 2
            continue
        if content.startswith(r"\]", i):
            in_display_math = False
            escaped_chars.append(r"\]")
            i += 2
            continue
        if content.startswith("$$", i):
            if in_display_math:
                in_display_math = False
            else:
                in_display_math = True
                last_display_math_index = len(escaped_chars)
            escaped_chars.append("$$")
            i += 2
            continue

        current_char = content[i]
        if current_char == "\\":
            if i + 1 < len(content):
                escaped_chars.append(content[i : i + 2])
                i += 2
                continue
            escaped_chars.append("\\")
            i += 1
            continue

        if current_char == "$":
            if in_inline_math:
                in_inline_math = False
            else:
                in_inline_math = True
                last_inline_math_index = len(escaped_chars)
            escaped_chars.append("$")
            i += 1
            continue

        in_math_mode = in_inline_math or in_display_math
        if not in_math_mode and current_char == "_":
            escaped_chars.append(r"\_")
        elif not in_math_mode and current_char == "^":
            escaped_chars.append(r"\^{}")
        elif not in_math_mode and current_char in {"#", "%", "&"}:
            escaped_chars.append(f"\\{current_char}")
        else:
            escaped_chars.append(current_char)
        i += 1

    if in_inline_math and last_inline_math_index is not None:
        escaped_chars[last_inline_math_index] = r"\$"
    if in_display_math and last_display_math_index is not None:
        escaped_chars[last_display_math_index] = r"\$\$"

    return "".join(escaped_chars).strip()


def prepare_latex_body(content: str) -> str | None:
    normalized = _extract_latex_document_body(_strip_markdown_code_fences(content))
    if not normalized:
        return None

    normalized = _normalize_markdown_headings(normalized)
    escaped = _escape_text_mode_special_chars(normalized)
    cleaned = escaped.strip()
    return cleaned or None


def _extract_tectonic_error_context(latex_document: str, stderr: str) -> str:
    match = TECTONIC_ERROR_LINE_RE.search(stderr)
    if not match:
        return ""

    line_number = int(match.group(1))
    error_message = match.group(2).strip()
    latex_lines = latex_document.splitlines()
    if line_number < 1 or line_number > len(latex_lines):
        return f"line {line_number}: {error_message}"

    start_line = max(1, line_number - 1)
    end_line = min(len(latex_lines), line_number + 1)
    context_parts: list[str] = []
    for current_line in range(start_line, end_line + 1):
        snippet = latex_lines[current_line - 1].strip()
        if len(snippet) > 120:
            snippet = f"{snippet[:117]}..."
        context_parts.append(f"{current_line}:{snippet}")

    return (
        f"line {line_number}: {error_message} | context: {' || '.join(context_parts)}"
    )


def looks_like_latex(text: str | None) -> bool:
    """Heuristic to determine if text contains LaTeX markup."""
    if not text:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    return bool(LATEX_TRIGGER_RE.search(stripped))


class MessagingService:
    _TOOL_NAME_MARKERS = tuple(tool_name.value for tool_name in ToolName)

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._settings_handlers = {
            "personal info": self._handle_personal_info_settings,
            "classes and subjects": self._handle_classes_subjects_settings,
        }
        self._command_handlers = {
            "settings": self._command_settings,
            "help": self._command_help,
        }

    async def handle_settings_selection(
        self, user: models.User, message: models.Message
    ) -> JSONResponse:
        self.logger.debug(f"Handling interactive message with title: {message.content}")
        key = (message.content or "").strip().lower()
        handler = self._settings_handlers.get(key)
        if handler is None:
            raise Exception(f"Unrecognized user reply: {message.content}")
        await handler(user)
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    @track_messages("settings_flow_personal_info")
    async def _handle_personal_info_settings(self, user: models.User) -> None:
        self.logger.debug("Sending update personal and school info flow")
        await flow_client.send_user_settings_flow(user)

    @track_messages("settings_flow_classes_subjects")
    async def _handle_classes_subjects_settings(self, user: models.User) -> None:
        self.logger.debug("Sending update class and subject info flow")
        await flow_client.send_subjects_classes_flow(user)

    async def handle_command_message(
        self, user: models.User, message: models.Message
    ) -> JSONResponse:
        self.logger.debug(f"Handling command message: {message.content}")
        assert message.content is not None
        key = message.content.lower()
        handler = self._command_handlers.get(key, self._command_unknown)
        await handler(user)
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    @track_messages("command_settings")
    async def _command_settings(self, user: models.User) -> None:
        response_text = strings.get_string(StringCategory.SETTINGS, "intro")
        options = [
            strings.get_string(StringCategory.SETTINGS, "personal_info"),
            strings.get_string(StringCategory.SETTINGS, "class_subject_info"),
        ]
        await whatsapp_client.send_message(user.wa_id, response_text, options)

    @track_messages("command_help")
    async def _command_help(self, user: models.User) -> None:
        response_text = strings.get_string(StringCategory.INFO, "help")
        await whatsapp_client.send_message(user.wa_id, response_text)

    @track_messages("command_unknown")
    async def _command_unknown(self, user: models.User) -> None:
        response_text = strings.get_string(StringCategory.ERROR, "command_not_found")
        await whatsapp_client.send_message(user.wa_id, response_text)

    async def handle_chat_message(
        self, user: models.User, user_message: models.Message
    ) -> JSONResponse:

        if llm_settings.agentic_mode:
            self.logger.info(
                "Agentic mode is enabled. Using AgentClient for response generation."
            )
            llm_responses = await agent_client.generate_response(
                user=user, message=user_message
            )
        else:
            self.logger.info(
                "Agentic mode is disabled. Using standard LLMClient for response generation."
            )
            llm_responses = await llm_client.generate_response(
                user=user, message=user_message
            )

        if llm_responses:
            assert llm_responses[-1].content is not None

            final_message = next(
                (
                    msg
                    for msg in reversed(llm_responses)
                    if msg.role == enums.MessageRole.assistant and msg.content
                ),
                None,
            )

            error_message = None

            if not final_message:
                self.logger.warning(
                    "No assistant response with content available; sending fallback."
                )
                await whatsapp_client.send_message(
                    user.wa_id, strings.get_string(StringCategory.ERROR, "general")
                )
                record_messages_generated("chat_error")

                error_message = models.Message.from_attributes(
                    user_id=user.id,
                    role=enums.MessageRole.assistant,
                    content=strings.get_string(StringCategory.ERROR, "general"),
                )

            llm_content = final_message.content
            if self._are_the_tools_names_mentioned(llm_content):
                self.logger.warning(
                    "Tool name leakage detected in LLM response; sending fallback message."
                )
                await whatsapp_client.send_message(
                    user.wa_id, strings.get_string(StringCategory.ERROR, "tool_leakage")
                )
                record_messages_generated("tool_names_mentioned_error")

                error_message = models.Message.from_attributes(
                    user_id=user.id,
                    role=enums.MessageRole.assistant,
                    content=strings.get_string(StringCategory.ERROR, "tool_leakage"),
                )

            if error_message is not None:
                messages_to_add = llm_responses + [error_message]
                await db.create_new_messages(messages_to_add)

                return JSONResponse(content={"status": "ok"}, status_code=200)

            await db.create_new_messages(llm_responses)

            self.logger.debug(f"Sending message to {user.wa_id}: {llm_content}")

            if looks_like_latex(llm_content):
                prepared_latex_content = prepare_latex_body(llm_content)
                latex_document_path = (
                    text_to_img(prepared_latex_content)
                    if prepared_latex_content is not None
                    else None
                )

                if latex_document_path:
                    image_sent = await whatsapp_client.send_image_message(
                        wa_id=user.wa_id,
                        image_path=latex_document_path,
                        img_type=ImageType.PNG,
                    )
                    if image_sent:
                        record_messages_generated("chat_response_with_latex_image")
                    else:
                        self.logger.warning(
                            "Falling back to plain text delivery; WhatsApp image send failed."
                        )
                        await whatsapp_client.send_message(user.wa_id, llm_content)
                        record_messages_generated(
                            "chat_response_with_latex_image_fallback"
                        )

                else:
                    self.logger.warning(
                        "Falling back to plain text delivery; LaTeX render failed."
                    )
                    await whatsapp_client.send_message(user.wa_id, llm_content)
                    record_messages_generated("chat_response_with_latex_image_fallback")

            else:
                await whatsapp_client.send_message(user.wa_id, llm_content)
                record_messages_generated("chat_response")

        else:
            err_message = strings.get_string(StringCategory.ERROR, "general")
            await whatsapp_client.send_message(user.wa_id, err_message)
            record_messages_generated("chat_error")

        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    def _are_the_tools_names_mentioned(self, message: str) -> bool:
        tool_names = self._TOOL_NAME_MARKERS
        if not tool_names:
            return False

        message_lower = message.lower()
        for tool_name in tool_names:
            if tool_name in message_lower:
                return True

        return False

    async def handle_other_message(
        self, user: models.User, user_message: models.Message
    ) -> JSONResponse:
        assert user.id is not None
        message = models.Message(
            user_id=user.id,
            role=enums.MessageRole.assistant,
            content=strings.get_string(StringCategory.ERROR, "unsupported_message"),
        )
        await db.create_new_message(message)
        # Send message to the user
        await whatsapp_client.send_message(
            user.wa_id, strings.get_string(StringCategory.ERROR, "unsupported_message")
        )
        record_messages_generated("unsupported_message")
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )


def _tectonic_artifact_name() -> str | None:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        if machine in ("arm64", "aarch64"):
            return "aarch64-apple-darwin"
        if machine in ("x86_64", "amd64"):
            return "x86_64-apple-darwin"
    elif system == "linux":
        if machine in ("x86_64", "amd64"):
            return "x86_64-unknown-linux-gnu"
        if machine in ("arm64", "aarch64"):
            return "aarch64-unknown-linux-musl"
    return None


def _ensure_tectonic_binary() -> str | None:
    existing_path = shutil.which("tectonic")
    if existing_path:
        return existing_path

    artifact = _tectonic_artifact_name()
    if artifact is None:
        return None

    cache_dir = os.path.join(TECTONIC_CACHE_ROOT, f"{TECTONIC_VERSION}-{artifact}")
    os.makedirs(cache_dir, exist_ok=True)
    binary_path = os.path.join(cache_dir, "tectonic")
    if os.path.exists(binary_path):
        return binary_path

    archive_name = f"tectonic-{TECTONIC_VERSION}-{artifact}.tar.gz"
    download_url = (
        "https://github.com/tectonic-typesetting/tectonic/releases/download/"
        f"tectonic%40{TECTONIC_VERSION}/{archive_name}"
    )
    archive_path = os.path.join(cache_dir, archive_name)

    try:
        with (
            request.urlopen(download_url) as response,
            open(archive_path, "wb") as archive_file,
        ):
            shutil.copyfileobj(response, archive_file)
    except Exception as exc:
        logging.getLogger(__name__).error("Failed to download Tectonic: %s", exc)
        return None

    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            archive.extractall(path=cache_dir)
    except Exception as exc:
        logging.getLogger(__name__).error("Failed to extract Tectonic archive: %s", exc)
        return None
    finally:
        try:
            os.remove(archive_path)
        except OSError:
            pass

    if os.path.exists(binary_path):
        current_mode = os.stat(binary_path).st_mode
        os.chmod(binary_path, current_mode | stat.S_IEXEC)
        return binary_path

    return None


def compile_latex_to_pdf(latex_body: str, temp_dir: str) -> str:
    """Compile a LaTeX string into a PDF stored in temp_dir using Tectonic."""
    logger = logging.getLogger(__name__)
    tectonic_path = _ensure_tectonic_binary()
    if tectonic_path is None:
        raise RuntimeError(
            "Tectonic binary is not available on this host and automatic download failed."
        )

    filename = f"llm_output_{uuid.uuid4().hex[:8]}"
    tex_filename = filename + ".tex"
    tex_path = os.path.join(temp_dir, tex_filename)
    pdf_path = os.path.join(temp_dir, filename + ".pdf")

    latex_document = LATEX_TEMPLATE.replace("__CONTENT__", latex_body)
    with open(tex_path, "w", encoding="utf-8") as tex_file:
        tex_file.write(latex_document)

    cmd = [tectonic_path, "--outdir", temp_dir, tex_filename]
    result = subprocess.run(
        cmd,
        cwd=temp_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0 or not os.path.exists(pdf_path):
        error_context = _extract_tectonic_error_context(latex_document, result.stderr)
        if error_context:
            logger.error("LaTeX compile context: %s", error_context)
        raise RuntimeError(
            "Tectonic failed with code "
            f"{result.returncode}: {result.stderr.strip()} "
            f"{error_context}".strip()
        )

    return pdf_path


def text_to_img(content: str) -> str | None:
    """
    Convert a LaTeX document body to a PNG image. Returns the path to the PNG image.
    """
    logger = logging.getLogger(__name__)
    temp_dir = tempfile.mkdtemp()
    output_file_descriptor, output_path = tempfile.mkstemp(
        prefix="twiga_latex_", suffix=".png"
    )
    os.close(output_file_descriptor)
    rendered_image_ready = False

    try:
        pdf_path = compile_latex_to_pdf(content, temp_dir)
    except Exception as exc:
        logger.error("Error compiling LaTeX: %s", exc)
        try:
            os.remove(output_path)
        except OSError:
            pass
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None

    try:
        pdf_document = fitz.open(pdf_path)
        try:
            page = pdf_document[0]
            for dpi in PDF_RENDER_DPI_CANDIDATES:
                pix = page.get_pixmap(dpi=dpi)
                pix.save(output_path)
                if os.path.getsize(output_path) <= WHATSAPP_MAX_IMAGE_SIZE_BYTES:
                    rendered_image_ready = True
                    return output_path
            logger.warning(
                "Generated image exceeds WhatsApp upload limit after DPI fallback (%s).",
                output_path,
            )
        finally:
            pdf_document.close()
    except Exception as exc:
        logger.error("Error converting LaTeX PDF to image: %s", exc)
        return None
    finally:
        if not rendered_image_ready and os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        shutil.rmtree(temp_dir, ignore_errors=True)


messaging_client = MessagingService()
