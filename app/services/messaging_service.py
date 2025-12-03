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
import app.database.enums as enums

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


class MessagingService:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def handle_settings_selection(
        self, user: models.User, message: models.Message
    ) -> JSONResponse:
        self.logger.debug(f"Handling interactive message with title: {message.content}")
        if message.content == "Personal Info":
            self.logger.debug("Sending update personal and school info flow")
            await flow_client.send_user_settings_flow(user)
        elif message.content == "Classes and Subjects":
            self.logger.debug("Sending update class and subject info flow")
            await flow_client.send_subjects_classes_flow(user)
        else:
            raise Exception(f"Unrecognized user reply: {message.content}")
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    async def handle_command_message(
        self, user: models.User, message: models.Message
    ) -> JSONResponse:
        self.logger.debug(f"Handling command message: {message.content}")
        assert message.content is not None
        if message.content.lower() == "settings":
            response_text = strings.get_string(StringCategory.SETTINGS, "intro")
            options = [
                strings.get_string(StringCategory.SETTINGS, "personal_info"),
                strings.get_string(StringCategory.SETTINGS, "class_subject_info"),
            ]
            await whatsapp_client.send_message(user.wa_id, response_text, options)
        elif message.content.lower() == "help":
            response_text = strings.get_string(StringCategory.INFO, "help")
            await whatsapp_client.send_message(user.wa_id, response_text)
        else:
            response_text = strings.get_string(
                StringCategory.ERROR, "command_not_found"
            )
            await whatsapp_client.send_message(user.wa_id, response_text)
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

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

            llm_content = llm_responses[-1].content

            if looks_like_latex(llm_content):
                latex_document_path = text_to_img(llm_content)

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
        with request.urlopen(download_url) as response, open(
            archive_path, "wb"
        ) as archive_file:
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

    tex_filename = "llm_output.tex"
    tex_path = os.path.join(temp_dir, tex_filename)
    pdf_path = os.path.join(temp_dir, "llm_output.pdf")

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
