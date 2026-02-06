# Database Schema

**N/A** - Beddel Python is a stateless SDK. State management is handled via:

1. **ExecutionContext:** In-memory during workflow execution
2. **Callbacks:** Users implement persistence via lifecycle hooks
3. **File-based state:** Optional pattern for agent-native workflows (post-MVP)
