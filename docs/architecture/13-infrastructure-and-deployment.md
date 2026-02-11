# 13. Infrastructure and Deployment

## 13.1 Infrastructure as Code

N/A for MVP — Beddel is an SDK distributed via PyPI, not a deployed service. Users deploy it within their own infrastructure.

## 13.2 Deployment Strategy

- **Strategy:** PyPI package distribution via `hatchling` build
- **CI/CD Platform:** GitHub Actions
- **Pipeline Configuration:** `.github/workflows/ci.yml` (PR checks), `.github/workflows/release.yml` (PyPI publish)

## 13.3 Environments

- **Development:** Local Python virtualenv with `pip install -e ".[dev]"`
- **CI:** GitHub Actions runners (Ubuntu latest, Python 3.11+)
- **Production:** PyPI package installed by end users (`pip install beddel`)

## 13.4 Environment Promotion Flow

```
Local Development → PR (CI checks) → main branch → Tag release → PyPI publish
```

## 13.5 Rollback Strategy

- **Primary Method:** PyPI version yanking + new patch release
- **Trigger Conditions:** Critical bug in published version, security vulnerability
- **Recovery Time Objective:** < 1 hour for new patch release

---
