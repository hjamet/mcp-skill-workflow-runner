---
name: work
description: Boucle socratique continue d'exploration, questionnement décisionnel et avancement proactif sur un projet. Explore les notes, lance des scouts, identifie les trous et ne pose à l'utilisateur QUE les questions décisionnelles dont il a véritablement besoin.
workflow:
  version: "1.0"
  type: "loop"
  initial_step: "step_1_exploration"
  
  context_schema:
    project:
      type: "string"
      required: true
      description: "Nom du projet cible"
    iteration:
      type: "integer"
      default: 1
      description: "Compteur d'itération du cycle"

  steps:
    - id: "step_1_exploration"
      title: "💡 Étape 1 : Exploration & Génération de Questions Candidates"
      section_matcher: "### 3.1"
      step_type: "standard"
      mandated_tools:
        - "view_file"
        - "recall"
      constraints:
        - "INTERDICTION ABSOLUE de poser une question sans avoir cherché au préalable"
      expected_outputs:
        - "candidate_questions_list"
      next: "step_2_scouts"

    - id: "step_2_scouts"
      title: "🔭 Étape 2 : Déploiement des Scouts sur Clusters Indépendants"
      section_matcher: "### 3.2"
      step_type: "subagent_barrier"
      subagent_recommendation:
        type: "research"
        clustering_rule: "1 sous-agent par périmètre orthogonal distinct (Code, Web, Mails, AIVC)"
        model: "flash"
      constraints:
        - "Règle de Découpage par Cluster Indépendant : K clusters = K sous-agents simultanés"
      next: "step_3_ask"

    - id: "step_3_ask"
      title: "🗣️ Étape 3 : Questionnement Décisionnel de l'Utilisateur"
      section_matcher: "### 3.3"
      step_type: "interactive"
      mandated_tools:
        - "ask_question"
      constraints:
        - "Poser 2 à 4 questions maximum par cycle"
        - "Zéro question triviale"
      next: "step_4_action"

    - id: "step_4_action"
      title: "🚀 Étape 4 : Déploiement des Sous-Agents d'Action & Mises à Jour"
      section_matcher: "### 3.4"
      step_type: "subagent_barrier"
      subagent_recommendation:
        type: "builder"
        clustering_rule: "Loi stricte N -> N (1 builder par tâche)"
      mandated_tools:
        - "write_to_file"
        - "remember"
      constraints:
        - "summary.md est le premier outil obligatoire (First Tool Call)"
        - "Loi stricte N -> N"
      next: "step_5_loop"

    - id: "step_5_loop"
      title: "🔄 Étape 5 : Relance Immédiate du Cycle"
      section_matcher: "### 3.5"
      step_type: "loop_decision"
      constraints:
        - "INTERDICTION DE S'ARRÊTER : ré-exécuter immédiatement l'Étape 1"
      next: "step_1_exploration"
---

# 🔄 Skill : Socratic Work Loop — Exploration Continue & Questionnement Décisionnel

### 3.1 — ### 💡 Étape 1 : Exploration & Génération de Questions Candidates

L'agent principal superviseur explore **directement** les notes du projet.
1. Lire la note maîtresse du projet (`view_file`).
2. Lire les sous-notes liées.
3. Consulter la mémoire AIVC (`recall`).
4. Générer une liste de questions candidates selon les 5 axes systématiques.

### 3.2 — ### 🔭 Étape 2 : Déploiement des Scouts sur Clusters Indépendants

Pour chaque question candidate, déployer autant de sous-agents `research` en parallèle qu'il y a de clusters indépendants orthogonaux.

### 3.3 — ### 🗣️ Étape 3 : Questionnement Décisionnel de l'Utilisateur (`ask_question`)

Poser les questions filtrées via l'outil `ask_question`. 2 à 4 questions maximum par cycle.

### 3.4 — ### 🚀 Étape 4 : Déploiement des Sous-Agents d'Action ($N \to N$) & Mises à Jour

Dès qu'Henri valide ses réponses, mettre à jour `summary.md` (First Tool Call) et lancer les sous-agents d'action.

### 3.5 — ### 🔄 Étape 5 : Relance Immédiate du Cycle (Retour à l'Étape 1)

Le superviseur ne s'arrête pas et ré-exécute immédiatement l'Étape 1 pour le cycle suivant.
