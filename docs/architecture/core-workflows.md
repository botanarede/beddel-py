# Core Workflows

> **Note:** Diagrams show FastAPI as an example integration. The core SDK can be used standalone or with any framework via optional extras.

## Workflow Execution Sequence

```mermaid
sequenceDiagram
    participant User
    participant FastAPI
    participant Executor as WorkflowExecutor
    participant Parser as YAMLParser
    participant Resolver as VariableResolver
    participant Registry as PrimitiveRegistry
    participant Primitive
    participant LiteLLM as LiteLLMAdapter
    participant Hooks as LifecycleHooks
    participant Tracer as OpenTelemetry

    User->>FastAPI: POST /agent/{name}
    FastAPI->>Parser: parse(yaml_content)
    Parser-->>FastAPI: WorkflowDefinition
    FastAPI->>Executor: execute(workflow, input)
    Executor->>Tracer: start_workflow_span()
    Executor->>Hooks: emit("workflow_start")
    
    loop For each step
        Executor->>Tracer: start_step_span()
        Executor->>Hooks: emit("step_start")
        Executor->>Resolver: resolve(step.config, context)
        Resolver-->>Executor: resolved_config
        Executor->>Registry: get(step.type)
        Registry-->>Executor: primitive_func
        Executor->>Primitive: execute(config, context)
        
        alt LLM Primitive
            Primitive->>LiteLLM: complete(request)
            LiteLLM-->>Primitive: LLMResponse
        end
        
        Primitive-->>Executor: step_result
        Executor->>Hooks: emit("step_end")
        Executor->>Tracer: end_step_span()
    end
    
    Executor->>Hooks: emit("workflow_end")
    Executor->>Tracer: end_workflow_span()
    Executor-->>FastAPI: ExecutionResult
    FastAPI-->>User: JSON Response
```

## SSE Streaming Sequence

```mermaid
sequenceDiagram
    participant User
    participant FastAPI
    participant Executor as WorkflowExecutor
    participant LLM as llm Primitive
    participant LiteLLM as LiteLLMAdapter

    User->>FastAPI: POST /agent/{name} (Accept: text/event-stream)
    FastAPI->>Executor: execute_stream(workflow, input)
    
    loop For each step
        Executor->>LLM: execute_stream(config, context)
        LLM->>LiteLLM: stream(request)
        
        loop For each chunk
            LiteLLM-->>LLM: LLMChunk
            LLM-->>Executor: yield chunk
            Executor-->>FastAPI: yield SSE event
            FastAPI-->>User: data: {chunk}
        end
    end
    
    FastAPI-->>User: event: done
```
