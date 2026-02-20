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

import fitz

from app.config import Environment, settings


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
MARKDOWN_BOLD_RE = re.compile(r"(?<![\\\w])\*\*(?=\S)(.+?)(?<=\S)\*\*(?!\w)")
MARKDOWN_ITALIC_RE = re.compile(r"(?<![\\\w])\*(?=\S)(.+?)(?<=\S)\*(?!\w)")
MARKDOWN_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.*?)\s*$")

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
    def to_latex_heading(level: int, text: str) -> str:
        if level == 1:
            return rf"\section*{{{text}}}"
        if level in (2, 3):
            return rf"\subsection*{{{text}}}"
        if level == 4:
            return rf"\subsubsection*{{{text}}}"
        return rf"\textbf{{{text}}}"

    normalized_lines: list[str] = []
    for line in content.splitlines():
        match = MARKDOWN_HEADING_RE.match(line)
        if match:
            level = len(match.group(1))
            heading_text = match.group(2)
            normalized_lines.append(to_latex_heading(level, heading_text))
            normalized_lines.append("")
            continue
        normalized_lines.append(line)
    return "\n".join(normalized_lines).strip()


def _convert_markdown_emphasis_in_text(content: str) -> str:
    content = MARKDOWN_BOLD_RE.sub(r"\\textbf{\1}", content)
    return MARKDOWN_ITALIC_RE.sub(r"\\emph{\1}", content)


def _convert_markdown_emphasis(content: str) -> str:
    converted_parts: list[str] = []
    text_buffer: list[str] = []
    in_inline_math = False
    in_display_math = False

    def flush_text_buffer() -> None:
        if text_buffer:
            converted_parts.append(
                _convert_markdown_emphasis_in_text("".join(text_buffer))
            )
            text_buffer.clear()

    i = 0
    while i < len(content):
        if content.startswith(r"\(", i):
            flush_text_buffer()
            in_inline_math = True
            converted_parts.append(r"\(")
            i += 2
            continue
        if content.startswith(r"\)", i):
            flush_text_buffer()
            in_inline_math = False
            converted_parts.append(r"\)")
            i += 2
            continue
        if content.startswith(r"\[", i):
            flush_text_buffer()
            in_display_math = True
            converted_parts.append(r"\[")
            i += 2
            continue
        if content.startswith(r"\]", i):
            flush_text_buffer()
            in_display_math = False
            converted_parts.append(r"\]")
            i += 2
            continue
        if content.startswith("$$", i):
            flush_text_buffer()
            in_display_math = not in_display_math
            converted_parts.append("$$")
            i += 2
            continue
        if content[i] == "$":
            flush_text_buffer()
            in_inline_math = not in_inline_math
            converted_parts.append("$")
            i += 1
            continue

        if in_inline_math or in_display_math:
            converted_parts.append(content[i])
        else:
            text_buffer.append(content[i])
        i += 1

    flush_text_buffer()
    return "".join(converted_parts)


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
    normalized = _convert_markdown_emphasis(normalized)
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


def _should_persist_latex_image_locally() -> bool:
    return settings.mock_whatsapp or settings.environment in (
        Environment.LOCAL,
        Environment.DEVELOPMENT,
    )


def looks_like_latex(text: str | None) -> bool:
    """Heuristic to determine if text contains LaTeX markup."""
    if not text:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    return bool(LATEX_TRIGGER_RE.search(stripped))


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
    output_dir = os.getcwd() if _should_persist_latex_image_locally() else None
    if output_dir is not None:
        os.makedirs(output_dir, exist_ok=True)
    output_file_descriptor, output_path = tempfile.mkstemp(
        prefix="twiga_latex_", suffix=".png", dir=output_dir
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
                    if output_dir is not None:
                        logger.info(
                            "Saved LaTeX image locally for debugging: %s",
                            output_path,
                        )
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
