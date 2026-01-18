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
from langchain_core.messages import SystemMessage, HumanMessage

import app.database.models as models
from app.services.flow_service import flow_client
from app.utils.string_manager import strings, StringCategory
from app.services.whatsapp_service import whatsapp_client, ImageType
import app.database.db as db
from app.services.llm_service import llm_client
import app.database.enums as enums
from app.monitoring.metrics import record_messages_generated, track_messages
from app.utils.llm_utils import async_llm_request


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

LATEX_TRIGGER_RE = re.compile(
    r"(\\begin\{|\\end\{|\\documentclass|\\usepackage|\\frac|\\sum|"
    r"\\int|\\sqrt|\\left|\\right|\\text\{|\\section|\\alpha|\\beta|"
    r"\\gamma|\\pi|\\theta|\\[|\\]|\\(|\\)|\$)"
)

LATEX_CONVERTER_SYSTEM_PROMPT = """
    You are a LaTeX transcriber.

    Task: Convert the user's input into LaTeX that can be inserted inside a document body.

    Hard rules:
    - Do NOT solve, answer, explain, or add any new content.
    - Do NOT remove any content.
    - Preserve the original meaning, order, and intent exactly.
    - If the input contains questions or instructions, keep them as text.
    - Only convert formatting to LaTeX (e.g., headings -> \section, lists -> itemize).
    - Keep all numbers, math expressions, and wording unchanged except for required LaTeX syntax.
    - Output ONLY LaTeX. No markdown, no preamble, no commentary.
    """

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


def looks_like_latex(text: str | None) -> bool:
    """Heuristic to determine if text contains LaTeX markup."""
    if not text:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    return bool(LATEX_TRIGGER_RE.search(stripped))


async def convert_text_to_latex(content: str) -> str | None:
    """Ask the LLM to convert arbitrary text into LaTeX-only content."""
    messages = [
        SystemMessage(content=LATEX_CONVERTER_SYSTEM_PROMPT),
        HumanMessage(content=content),
    ]
    try:
        response = await async_llm_request(
            messages=messages,
            tools=None,
            tool_choice=None,
            run_name="latex_conversion",
            temperature=0.0,
            metadata={"phase": "latex_conversion"},
        )
    except Exception as exc:
        logging.getLogger(__name__).warning("Latex conversion request failed: %s", exc)
        return None

    converted = response.content
    if isinstance(converted, str):
        cleaned = converted.strip()
    elif isinstance(converted, list):
        pieces = []
        for chunk in converted:
            if isinstance(chunk, str):
                pieces.append(chunk)
            elif isinstance(chunk, dict) and "text" in chunk:
                pieces.append(chunk["text"])
        cleaned = "".join(pieces).strip()
    else:
        cleaned = str(converted).strip()

    return cleaned or None


class MessagingService:
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
        llm_responses = await llm_client.generate_response(
            user=user, message=user_message
        )
        if llm_responses:
            self.logger.debug(
                f"Sending message to {user.wa_id}: {llm_responses[-1].content}"
            )

            # Update the database with the responses
            await db.create_new_messages(llm_responses)

            assert llm_responses[-1].content is not None
            # Send the last message back to the user
            await whatsapp_client.send_message(user.wa_id, llm_responses[-1].content)
            record_messages_generated("chat_response", len(llm_responses))

            final_message = next(
                (
                    msg
                    for msg in reversed(llm_responses)
                    if msg.role == enums.MessageRole.assistant and msg.content
                ),
                None,
            )

            if not final_message:
                self.logger.warning(
                    "No assistant response with content available; sending fallback."
                )
                await whatsapp_client.send_message(
                    user.wa_id, strings.get_string(StringCategory.ERROR, "general")
                )
                return JSONResponse(content={"status": "ok"}, status_code=200)

            llm_content = final_message.content

            # TODO: all this part must be improved. Main goal is to avoid the extra LLM call.
            if looks_like_latex(llm_content):
                latex_ready_content = await convert_text_to_latex(llm_content)

                if latex_ready_content is None:
                    self.logger.warning(
                        "Latex conversion returned empty result; using original content."
                    )
                    latex_ready_content = llm_content

                latex_document_path = text_to_img(latex_ready_content)

                if latex_document_path:
                    # Send the LaTeX document as an image via WhatsApp
                    await whatsapp_client.send_image_message(
                        wa_id=user.wa_id,
                        image_path=latex_document_path,
                        img_type=ImageType.PNG,
                    )
                else:
                    self.logger.warning(
                        "Falling back to plain text delivery; LaTeX render failed."
                    )
                    await whatsapp_client.send_message(user.wa_id, llm_content)
            else:
                await whatsapp_client.send_message(user.wa_id, llm_content)

        else:
            err_message = strings.get_string(StringCategory.ERROR, "general")
            await whatsapp_client.send_message(user.wa_id, err_message)
            record_messages_generated("chat_error")

        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

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
        raise RuntimeError(
            f"Tectonic failed with code {result.returncode}: {result.stderr.strip()}"
        )

    return pdf_path


def text_to_img(content: str) -> str | None:
    """
    Convert a LaTeX document body to a PNG image. Returns the path to the PNG image.
    """
    temp_dir = tempfile.mkdtemp()
    output_path = f"output_{uuid.uuid4().hex[:8]}.png"

    try:
        pdf_path = compile_latex_to_pdf(content, temp_dir)
    except Exception as exc:
        print(f"Error compiling LaTeX: {exc}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None

    try:
        pdf_document = fitz.open(pdf_path)
        try:
            page = pdf_document[0]
            pix = page.get_pixmap(dpi=300)
            pix.save(output_path)
        finally:
            pdf_document.close()
        return output_path
    except Exception as exc:
        print(f"Error converting LaTeX PDF to image: {exc}")
        return None
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


messaging_client = MessagingService()
