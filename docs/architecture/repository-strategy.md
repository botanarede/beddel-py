# Repository Strategy

## Overview

O Beddel usa uma estratégia de **Monorepo → Polyrepo** em fases:

| Fase | Estrutura | Critério de Transição |
|------|-----------|----------------------|
| **Fase 1** | Monorepo único | Python MVP funcional |
| **Fase 2** | Monorepo com múltiplos SDKs | Python + TypeScript com paridade 100% |
| **Fase 3** | Repositórios separados | Quando manutenção independente for necessária |

## Fase 1: Monorepo Inicial (Atual)

```
botanarede/beddel/
├── spec/                           # Especificação compartilhada
│   ├── schemas/                    # JSON Schema para YAML workflows
│   ├── fixtures/                   # YAML fixtures para testes cross-SDK
│   └── docs/                       # Documentação da especificação
│
├── src/
│   └── beddel-py/                  # Python SDK (MVP)
│       ├── pyproject.toml
│       ├── src/beddel/
│       ├── tests/
│       └── examples/
│
├── docs/                           # Documentação do projeto
│   ├── brief.md
│   ├── prd.md
│   └── architecture.md
│
├── .bmad-core/                     # BMAD Method
└── README.md
```

## Fase 2: Múltiplos SDKs no Monorepo

```
botanarede/beddel/
├── spec/                           # Especificação compartilhada (source of truth)
│
├── src/
│   ├── beddel-py/                  # Python SDK
│   ├── beddel-ts/                  # TypeScript SDK (traduzido de Python)
│   ├── beddel-go/                  # Go SDK (futuro)
│   ├── beddel-php/                 # PHP SDK (futuro)
│   ├── beddel-java/                # Java SDK (futuro)
│   ├── beddel-rust/                # Rust SDK (futuro)
│   └── beddel-{lang}/              # Qualquer linguagem/tecnologia
│
├── tools/                          # Ferramentas de desenvolvimento
│   ├── translator/                 # AI-assisted SDK translation
│   └── validator/                  # Cross-SDK fixture validation
│
└── docs/
```

## Fase 3: Repositórios Separados (Futuro)

Quando a manutenção independente for necessária:

```
botanarede/beddel-spec              # Especificação (git submodule nos SDKs)
botanarede/beddel-py                # Python SDK
botanarede/beddel-ts                # TypeScript SDK
botanarede/beddel-go                # Go SDK
botanarede/beddel-{lang}            # Outros SDKs
```

**Critérios para separação:**
- Ciclos de release independentes necessários
- Times diferentes mantendo SDKs diferentes
- Complexidade do monorepo impactando CI/CD

## Estratégia de Tradução

Python é o **Single Source of Truth** para tradução:

```
Python SDK (source) → AI Translation → Target SDK → Validation (spec/fixtures)
```

1. **Implementar em Python** com testes completos
2. **Traduzir via AI** usando spec + código Python como contexto
3. **Validar paridade** executando fixtures compartilhados
4. **Iterar** até 100% de compatibilidade

## Versionamento

Todos os SDKs seguem **SemVer sincronizado**:

| Componente | Versão | Notas |
|------------|--------|-------|
| `spec` | 1.x.x | Define compatibilidade |
| `beddel-py` | 1.x.x | Segue spec |
| `beddel-ts` | 1.x.x | Segue spec |
| `beddel-*` | 1.x.x | Todos sincronizados |
