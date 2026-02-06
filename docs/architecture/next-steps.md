# Next Steps

## For Product Owner

1. Review this architecture document against PRD requirements
2. Execute PO master checklist: `@po *execute-checklist-po`
3. Shard PRD into epics: `@po *shard-prd`

## For Scrum Master

After PO approval:
1. Shard architecture: `@architect *shard-prd`
2. Draft first story: `@sm *draft` (start with E1.1: YAML Parser)

## For Developer

After story approval:
1. Set up project structure per Source Tree
2. Implement story: `@dev` with story file

## Architect Prompt (Frontend)

**N/A** - Beddel Python is an SDK without UI components. No frontend architecture required.
