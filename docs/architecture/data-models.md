# Data Models

## WorkflowDefinition

**Purpose:** Root model representing a complete YAML workflow file.

**Key Attributes:**
- `metadata`: WorkflowMetadata - Workflow identity (name, version, description)
- `workflow`: list[StepDefinition] - Ordered list of workflow steps
- `config`: WorkflowConfig - Global workflow configuration (default provided)
- `return_template`: dict | None - Optional explicit API response contract (YAML alias: `return`)

**Relationships:**
- Contains multiple `StepDefinition` instances
- References `WorkflowConfig` for global settings

**Return Template Behavior:**
The `return` property defines the exact shape of the API response:

| Scenario | Behavior |
|----------|----------|
| `return` defined | Resolve template and return (clean contract) |
| Last step has no `result` | Return last step's output directly |
| Otherwise | Return all accumulated variables |

**Example:**
```yaml
metadata:
  name: "Newsletter Signup"
  version: "1.0.0"

workflow:
  - id: "analyze"
    type: "llm"
    config: { ... }
    result: "analysis"

  - id: "save"
    type: "notion"
    config: { ... }
    result: "notionResult"

# Explicit API response shape
return:
  success: true
  pageId: "$stepResult.notionResult.pageId"
  summary: "$stepResult.analysis.text"
```

## StepDefinition

**Purpose:** Represents a single step within a workflow.

**Key Attributes:**
- `id`: str - Unique step identifier within workflow
- `type`: str - Primitive type (llm, chat, output-generator, etc.)
- `config`: dict - Primitive-specific configuration
- `result`: str | None - Variable name to store step output in context (used as key in `$stepResult.*`)
- `condition`: str | None - Optional execution condition
- `on_error`: ErrorHandler | None - Error handling configuration

**Relationships:**
- Belongs to `WorkflowDefinition`
- References a primitive type from `PrimitiveRegistry`

## ExecutionContext

**Purpose:** Runtime state container for workflow execution.

**Key Attributes:**
- `workflow_id`: str - Unique execution identifier
- `input`: dict - Original input data
- `step_results`: dict[str, Any] - Results keyed by step's `result` variable name (not step ID)
- `env`: dict[str, str] - Environment variables snapshot
- `metadata`: dict - Execution metadata (timestamps, trace IDs)

**Relationships:**
- Created per workflow execution
- Passed to all primitives during execution

## LLMRequest / LLMResponse

**Purpose:** Standardized request/response models for LLM interactions.

**Key Attributes (Request):**
- `model`: str - Model identifier (e.g., "openrouter/anthropic/claude-3")
- `messages`: list[Message] - Conversation messages
- `temperature`: float - Sampling temperature
- `max_tokens`: int | None - Maximum response tokens
- `response_format`: dict[str, Any] | None - Structured output schema (JSON Schema dict)

**Key Attributes (Response):**
- `content`: str - Response content (plain text)
- `model`: str - Actual model used
- `usage`: TokenUsage - Token consumption details
- `finish_reason`: str - Completion reason

**Relationships:**
- Used by `llm` and `chat` primitives
- Processed by `LiteLLMAdapter`
