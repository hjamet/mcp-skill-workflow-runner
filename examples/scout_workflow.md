---
name: scout
description: Éclaireur de code et d'architecture.
workflow:
  version: "1.0"
  type: "dag"
  initial_step: "step_1_intake"
  
  context_schema:
    mode:
      type: "string"
      enum: ["standard", "A", "B", "hybrid"]
      default: "standard"
      
  steps:
    - id: "step_1_intake"
      title: "🎯 Prise de Mission & Classification"
      section_matcher: "## 1. 🎯 Prise de Mission"
      step_type: "standard"
      transitions:
        - condition: "context.get('mode') == 'A'"
          target: "step_2_mode_a"
        - condition: "context.get('mode') == 'B'"
          target: "step_2_mode_b"
        - condition: "context.get('mode') == 'hybrid'"
          target: "step_2_mode_hybrid"
        - default: "step_2_exploration"

    - id: "step_2_exploration"
      title: "🔍 Exploration en Profondeur Standard"
      section_matcher: "## 2. 🔍 Exploration en Profondeur"
      step_type: "standard"
      next: "step_3_synthesis"

    - id: "step_2_mode_a"
      title: "🔍 Exploration Mode A (K Axes Décomposés)"
      section_matcher: "### 2.4"
      step_type: "subagent_barrier"
      next: "step_3_synthesis"

    - id: "step_2_mode_b"
      title: "🔍 Exploration Mode B (N Agents Redondants)"
      section_matcher: "### 2.4"
      step_type: "subagent_barrier"
      next: "step_3_synthesis"

    - id: "step_2_mode_hybrid"
      title: "🔍 Exploration Mode Hybride"
      section_matcher: "### 2.4"
      step_type: "subagent_barrier"
      next: "step_3_synthesis"

    - id: "step_3_synthesis"
      title: "📊 Synthèse des Découvertes"
      section_matcher: "## 3. 📊 Synthèse des Découvertes"
      step_type: "standard"
      next: "step_4_deliverable"

    - id: "step_4_deliverable"
      title: "📝 Livrable exploration_report.md"
      section_matcher: "## 4. 📝 Livrable"
      step_type: "terminal"
      mandated_tools:
        - "write_to_file"
---

# Scout Workflow

## 1. 🎯 Prise de Mission

Analyse de la demande utilisateur et classification du mode d'exploration.

## 2. 🔍 Exploration en Profondeur

Exploration approfondie du codebase, du web et des logs.

### 2.4 Sous-Agents d'Exploration

Délégation multi-agents selon le mode (A, B, Hybride).

## 3. 📊 Synthèse des Découvertes

Agrégation et consolidation des résultats d'exploration.

## 4. 📝 Livrable

Génération du livrable unique `exploration_report.md`.
