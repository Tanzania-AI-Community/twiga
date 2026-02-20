# Tools Documentation

This package contains all the tool calls available to Twiga. Each tool is isolated in its own folder under `app/tools/tool_code/`.

## Current Tools

- **search_knowledge** - Retrieves relevant information from the knowledge base (TIE textbooks)
- **generate_exercise** - Generates practice questions based on course literature
- **solve_equation** - Solves mathematical equations with step-by-step solutions

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

a) Add tool name to ToolName enum:

b) Add tool metadata to `tools_metadata` list


### 3. Connect Tool in Tool Manager

Update `app/tools/tool_manager.py`:

a) Import tool function

b) Add case to `process_tool_calls` method


### 4. Update System Prompts

Add tool usage guidance to the agent's system prompts:

- `app/assets/prompts/twiga_agent_system` - For the main agent
- `app/assets/prompts/twiga_system` - For the LLM service

Add appropriate instructions in the tool usage section describing when and how to use your tool.

### 5. Add User-Facing Message

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

**Run tests:**
```bash
docker-compose -f docker/dev/docker-compose.yml exec app uv run pytest tests/test_<TOOL_NAME>.py -v -s
```

This allows you to verify tool calls work correctly without needing to interact with the full system.
