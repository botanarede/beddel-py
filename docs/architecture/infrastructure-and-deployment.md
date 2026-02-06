# Infrastructure and Deployment

## Infrastructure as Code

- **Tool:** N/A (SDK, not deployed infrastructure)
- **Location:** N/A
- **Approach:** Users deploy their own applications using Beddel

## Deployment Strategy

- **Strategy:** PyPI package distribution
- **CI/CD Platform:** GitHub Actions
- **Pipeline Configuration:** `.github/workflows/`

## Environments

- **Development:** Local development with `pip install -e .`
- **Testing:** pytest with mocked LLM calls
- **Production:** User's infrastructure (Beddel is a library)

## Package Distribution

```
Local Dev → pytest → Build (hatchling) → PyPI (twine) → User Install (pip)
```

## Rollback Strategy

- **Primary Method:** Semantic versioning with pinned dependencies
- **Trigger Conditions:** Breaking changes, critical bugs
- **Recovery Time Objective:** Users pin to previous version
