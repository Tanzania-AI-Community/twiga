# Tools Documentation

This package contains all the tool calls available to Twiga. Each tool is isolated in its own folder under `app/tools/tool_code/`.

## Current Tools

- **search_knowledge** - Retrieves relevant information from the knowledge base (TIE textbooks)
- **create_lesson_plan** - Creates a lesson plan scaffold based on class context and topic
- **generate_exercise** - Generates practice questions based on course literature
- **solve_equation** - Solves mathematical equations with step-by-step solutions
- **generate_necta_style_exam** - Generates exams based on course literature using the NECTA style

## Adding a New Tool

Follow these steps to add a new tool to Twiga:

### 1. Create Tool Structure

Create a new folder under `app/tools/tool_code/` with your tool name:

```
app/tools/tool_code/
  └── <TOOL_NAME>/
      ├── __init__.py
      └── main.py
```

The `main.py` file should contain your tool's main function.

### 2. Register Tool in Registry

Update `app/tools/registry.py`:

a) Add tool name to `ToolName` enum

b) Add function to `TOOL_FUNCTION_MAP` dictionary

c) Add tool metadata to `TOOLS_METADATA` list

d) (Optional) Add hidden internal arguments in `app/tools/internal_args.py`

Use this when a tool needs backend context (for example `user_id`) that the agent should not see or generate.

Example:
```python
from app.tools.registry import ToolName

def _build_<tool_name>_internal_args(user):
    if user.id is None:
        raise ValueError("Cannot inject internal args: user.id is None.")
    return {"user_id": user.id}

INTERNAL_TOOL_ARGS_MAPPING = {
    ToolName.<TOOL_NAME>.value: _build_<tool_name>_internal_args,
}
```

Notes:
- `ToolManager` loads these args via `get_internal_tool_args(...)`, merges them with LLM args, and validates the final signature before invoking the tool.
- Do not add internal-only args to `TOOLS_METADATA` (so they stay hidden from the agent).
- Ensure the tool function signature accepts the internal args.


### 3. Update System Prompts

Add tool usage guidance to the agent's system prompts:

- `app/assets/prompts/twiga/agent/system/` - For the main agent
- `app/assets/prompts/twiga/standard/system/` - For the LLM service

Add appropriate instructions in the tool usage section describing when and how to use your tool.

#### Prompt folders and versions

Prompts live under `app/assets/prompts/`, grouped by tool, then by variant or step
where needed, and finally by role (`system` or `user`). Each role folder contains
version files such as `v0.0` and `v0.1`. For example:

```text
equation_solver/standard/system/v0.0
equation_solver/concise/user/v0.0
lesson_plan/objectives/system/v0.0
exercise_generator/user/v0.0
```

Register each prompt in `app/assets/config/prompts.yml`:

```yaml
prompts:
  equation_solver_system:
    path: equation_solver/standard/system
    active_version: v0.0
    versions:
      v0.0:
        description: "Baseline version."
```

The required `path` is a folder relative to `app/assets/prompts/`; it does not
include the version filename. `PromptManager` loads every version listed in
`versions` from that folder. `active_version` must be one of those versions and
is used unless the caller supplies an explicit version.

Python callers use the registry name, for example
`prompt_manager.format_prompt("equation_solver_system")`. Moving a prompt folder
requires updating its `path`, but callers can stay unchanged when the registry
name stays the same. When adding a version, create its file and register it under
`versions`; update `active_version` when it should become the default.

### 4. Add User-Facing Message

Update `app/assets/strings/english.yml` to add a loading message for your tool:

```yaml
tools:
  <TOOL_NAME>: "⏳ Processing your request, please hold..."
```

## Testing Tools

### Manual Testing
Test by chatting with the agent in the mock WhatsApp interface.

### Integration Testing

**Important:** Integration tests should NOT call external LLMs since they run on GitHub Actions.

1. Create a test file in `tests/` directory (e.g., `test_<TOOL_NAME>.py`)
2. Write tests that verify the tool's logic without LLM calls
3. Mock any LLM dependencies

### End-to-End Testing with LLM

For testing that requires LLM calls, create a script in the `scripts/tools/` directory. It can be run with:

**Start Docker services:**
```bash
docker-compose -f docker/dev/docker-compose.yml up -d
```

**Run test script:**
```bash
docker-compose -f docker/dev/docker-compose.yml --env-file .env run --rm app bash -c "PYTHONPATH=/app uv run python scripts/tools/test_<TOOL_NAME>.py"
```

This allows you to verify tool calls work correctly without needing to interact with the full system.
