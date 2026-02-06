# Data Models

## WorkflowDefinition

**Purpose:** Root model representing a complete YAML workflow file.

**Key Attributes:**
- `name`: str - Workflow identifier
- `description`: str | None - Human-readable description
- `version`: str - Semantic version
- `input_schema`: dict | None - Pydantic schema for input validation
- `steps`: list[StepDefinition] - Ordered list of workflow steps
- `config`: WorkflowConfig - Global workflow configuration
- `return_template`: dict | None - Optional explicit API response contract

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
- `step_results`: dict[str, Any] - Results keyed by step ID
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
- `response_format`: type[BaseModel] | None - Structured output schema

**Key Attributes (Response):**
- `content`: str | BaseModel - Response content
- `model`: str - Actual model used
- `usage`: TokenUsage - Token consumption details
- `finish_reason`: str - Completion reason

**Relationships:**
- Used by `llm` and `chat` primitives
- Processed by `LiteLLMAdapter`
