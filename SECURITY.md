# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅        |

## Reporting a Vulnerability

Email security concerns to the maintainers via GitHub Issues with the `security` label.

## Dependency Security

### litellm pin (`<1.82.7`)

Beddel depends on litellm (optional, via `beddel[adapters]`). Versions 1.82.7 and 1.82.8 were compromised in a supply chain attack ([BerriAI/litellm#24512](https://github.com/BerriAI/litellm/issues/24512)). The malicious versions have been removed from PyPI.

Beddel pins `litellm>=1.40,<1.82.7` to exclude both affected versions. This constraint will be relaxed once a verified clean release is available upstream.
