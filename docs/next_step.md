# 📊 Gap Analysis: Handbook vs Brief.md

> **Date:** February 3, 2026  
> **Source:** [agent-native-handbook-analysis.md](file:///home/bacelar/www/beddel/ai-factory/beddel-py/agent-native-handbook-analysis.md)

---

## 1. Handbook Sections NOT INCLUDED in Brief

| Handbook Section | Missing Content | Impact |
|------------------|-----------------|--------|
| **2.1 LLMs / Generative AI** | Context-window limits, Prompt design (Chain-of-Thought, Tree-of-Thought), Model-specific quirks | High |
| **2.3 Reinforcement Learning & Agent Fine-Tuning** | Agent RFT on tool-use trajectories, Variance-Based RL, Oracle/Worker pattern | Medium |
| **2.4 Reasoning & Search Techniques** | Tree-of-Thought / Graph-of-Thought, Language Agent Tree Search (LATS) | High |
| **2.5 Multi-Agent / Swarm Systems** | Swarm Migration, Specialization vs. generalization, Coordination patterns | Medium |
| **2.6 Memory & Context Management** | Curated Code Context, Context Window Anxiety Management | Medium |
| **2.7 Feedback & Iterative Improvement** | Rich Feedback Loops (CI-feedback), Graph-of-Thought details | Medium |
| **2.8 Human-AI Collaboration** | Spectrum of Control / Blended Initiative, Chain-of-Thought Monitoring, Abstracted Code Representation | High |
| **2.9 Security & Safety** | Lethal Trifecta Threat Model, Compartmentalization, Egress Lockdown | High |
| **2.10 Learning & Adaptation** | Skill Library Evolution, Compounding Engineering Pattern, Continuous improvement via trajectories | High |

---

## 2. Anti-Patterns NOT MENTIONED in Brief

| Anti-Pattern | Description | Why It Matters |
|--------------|-------------|----------------|
| **Agent as Router** | Using agent only for routing, not action | Underutilizes agent capabilities |
| **Build the App, Then Add Agent** | Build features in code, expose to agent later | No emergent capability |
| **Request/Response Thinking** | Single pipeline without operation loops | Misses goal-oriented execution |
| **Defensive Tool Design** | Over-constraining tool inputs | Prevents unexpected agent actions |
| **Happy Path in Code** | Code handles edge cases, agent just executes | Agent becomes mere caller |

---

## 3. Agent-Native Principles PARTIALLY COVERED

| Principle | In Brief | Missing Details |
|-----------|----------|-----------------|
| **Parity** | ⚠️ Mentioned | Capability Map Pattern, Validation Test template |
| **Model Tier** | ✅ Yes | — |
| **File-based State** | ⚠️ Partial | Detailed Naming Patterns, `agent_log.md` concept |
| **Approval Patterns** | ✅ Yes | Stakes × Reversibility matrix examples |
| **On-device vs Cloud** | ❌ No | Server-side orchestrator for long-running agents |

---

## 4. Detailed Missing Concepts

### 4.1 Learning & Adaptation (Section 2.10)

**Not in Brief:**
- **Skill Library Evolution** - Dynamic skill creation and registration
- **Compounding Engineering Pattern** - Accumulative improvement over time
- **Continuous improvement via trajectories** - Learning from successful agent runs

**Implication for Beddel Python:**
```yaml
# Potential future feature: Agent-created skills
workflow:
  - id: "learn"
    type: "skill-learn"
    config:
      trajectory: "$stepResult.successfulRun"
      register_as: "new-skill-name"
```

### 4.2 Security & Safety (Section 2.9)

**Not in Brief:**
- **Lethal Trifecta Threat Model** - Security framework for agentic systems
- **Compartmentalization** - Isolating agent capabilities
- **Egress Lockdown** - Controlling agent external communications

### 4.3 Human-AI Collaboration (Section 2.8)

**Not in Brief:**
- **Spectrum of Control** - Full autonomy ↔ Full human control continuum
- **Blended Initiative** - Human and agent share control dynamically
- **Chain-of-Thought Monitoring** - Real-time visibility into agent reasoning
- **Abstracted Code Representation** - Simplified code views for agent context

### 4.4 Reasoning Techniques (Section 2.4)

**Not in Brief:**
- **Tree-of-Thought** - Branching reasoning paths
- **Graph-of-Thought** - Non-linear reasoning with cycles
- **Language Agent Tree Search (LATS)** - Search-based agent planning

---

## 5. Recommended Actions

### High Priority (Add to Brief)

1. [ ] Add Security & Safety section with Lethal Trifecta model
2. [ ] Expand Human-AI Collaboration with Spectrum of Control
3. [ ] Include Learning & Adaptation concepts (Skill Evolution)
4. [ ] Document anti-patterns to avoid

### Medium Priority (Add to PRD)

5. [ ] Add Tree-of-Thought reasoning as future primitive
6. [ ] Include Multi-Agent coordination patterns
7. [ ] Document Context Window management strategies

### Low Priority (Research Phase)

8. [ ] Investigate Agent RFT on trajectories
9. [ ] Research Swarm Migration patterns
10. [ ] Evaluate LATS implementation complexity

---

## 6. References

- [Handbook Analysis](file:///home/bacelar/www/beddel/ai-factory/beddel-py/agent-native-handbook-analysis.md) - Full analysis document
- [Brief](file:///home/bacelar/www/beddel/ai-factory/beddel-py/docs/brief.md) - Current project brief
- [PRD](file:///home/bacelar/www/beddel/ai-factory/beddel-py/docs/prd.md) - Product requirements
