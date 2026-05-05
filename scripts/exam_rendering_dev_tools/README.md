# Exam Rendering Dev Tools

This folder is for iterating on LaTeX exam and solution layout before moving final logic into the production Python renderers.

## Recommended Workflow

1. Prototype layout changes in this folder (`.tex`, sample JSON, generated outputs).
2. Compile locally for quick visual feedback.
3. After layout is correct, port the final structure into:
   - `app/services/exam_rendering/latex_exam_pdf_rendering.py`
   - `app/services/exam_rendering/latex_exam_solution_pdf_rendering.py`

For small spacing and formatting tweaks, compiling directly from VS Code LaTeX tools is usually much faster than running the full pipeline each time.

## Scripts

- `test_exam_pdf_rendering.py`
  - Runs full exam + solution rendering to PDFs from sample JSON.
- `create_exam_tex_file.py`
  - Generates only the raw exam `.tex` file (no PDF compilation).
- `create_exam_solution_tex_file.py`
  - Generates only the raw solution `.tex` file (no PDF compilation).

## Ownership of Content

- Exam structure/content (shared base used by both exam and solution) belongs in:
  - `latex_exam_pdf_rendering.py`
- Solution-only additions (answer blocks, marking schemes, etc.) belong in:
  - `latex_exam_solution_pdf_rendering.py`

The solution renderer should layer solution content on top of the base exam layout, without altering the core exam question structure.
