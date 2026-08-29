# ⚙️ MCP Server: skill-workflow-runner — Directives d'Intégration Antigravity

Serveur FastMCP implémentant l'architecture de **Divulgation Progressive Déterministe (*Deterministic Progressive Disclosure*)** pour l'exécution des workflows et compétences Antigravity.

---

## 🎯 Rôle et Philosophie Fondamentale

Lorsqu'un utilisateur invoque ou nécessite l'exécution d'un workflow structuré (notamment via les compétences ou commandes `/work`, `/scout`, `/refine`, `/build`, `/literature-review`), l'agent Antigravity **ne doit jamais exécuter l'ensemble du workflow en aveugle ou d'un seul bloc**.

Le serveur `skill-workflow-runner` agit comme l'**orchestrateur déterministe d'état** :
1. **Contrôle d'État Atomique Mono-Projet** : L'état du workflow, ses variables, son graphe DAG, ses transitions conditionnelles et son historique sont stockés de manière transactionnelle et persistée dans `~/.gemini/antigravity/workflow_sessions/`. La session active unique est gérée de façon 100% transparente.
2. **Divulgation Progressive Étape par Étape** : L'agent reçoit uniquement l'enveloppe directive (`StepResultEnvelope`) de l'étape courante, contenant la description, les directives markdown délimitées, les outils obligatoires (`mandated_tools`), les contraintes (`constraints`), et les recommandations de sous-agents (`subagent_recommendation`).
3. **Zéro Fallback Silencieux** : Toute erreur de résolution de fichier, de schéma YAML, de syntaxe d'expression dans les conditions ou de graphe DAG invalide déclenche une exception typée explicite.

---

## 🛠️ Catalogue des 3 Outils MCP

### 1. `start_workflow`
*Initialise l'exécution d'un workflow pour une compétence donnée.*
- **Arguments** :
  - `skill_name` *(string, obligatoire)* : Nom du skill (ex: `"work"`, `"scout"`, `"refine"`, `"build"`, `"literature-review"`) ou chemin direct vers un fichier `SKILL.md` / `workflow.md`.
  - `restart` *(boolean, optionnel, défaut `false`)* : Réinitialise/remplace toute session active si `true`, ou réutilise la session active existante pour ce workflow si `false`.
  - `initial_context` *(object, optionnel)* : Dictionnaire des variables de contexte initiales (ex: `{"mode": "B", "topic": "VoiceNotes"}`).
  - `workspace_dir` *(string, optionnel)* : Répertoire racine du projet courant pour la résolution locale (`.agent/skills/`, `skills/`).
- **Retour** : `StepResultEnvelope` de l'étape d'initialisation (généralement Étape 1).

### 2. `next_step`
*Valide le livrable de l'étape courante, évalue le DAG et passe à l'étape suivante sur la session active.*
- **Arguments** :
  - `user_response` *(string, optionnel)* : Réponse ou livrable textuel produit à l'étape courante.
  - `step_output` *(string ou object, optionnel)* : Livrable structuré ou dictionnaire de données produit.
  - `transition_choice` *(string, optionnel)* : Choix explicite de transition si plusieurs branches non conditionnelles sont possibles.
  - `variables` *(object, optionnel)* : Mises à jour des variables de contexte du workflow.
- **Retour** : `StepResultEnvelope` de la nouvelle étape active ou rapport de complétion si le workflow est terminé.

### 3. `end_workflow`
*Clôture explicitement la session active avec génération de métriques et rapport d'audit.*
- **Arguments** :
  - `final_summary` *(string, optionnel)* : Synthèse finale de la mission ou conclusion.
  - `status` *(string, défaut `"completed"`)* : Statut de clôture (`"completed"`, `"aborted"`, `"paused"`, `"failed"`).
- **Retour** : Rapport complet d'exécution (`closure_report`) contenant la durée totale, le nombre de cycles et l'historique complet des étapes franchies.

---

## 📋 Protocole d'Exécution par Workflow / Skill

### 🔹 `/work` (Workflow Opérationnel Structuré)
1. Invoquer `start_workflow(skill_name="work", initial_context={"task_description": "...", "mode": "..."})`.
2. Pour chaque étape reçue dans la directive :
   - Respecter scrupuleusement les `mandated_tools` (ex: `grep_search`, `find_by_name`, `replace_file_content`).
   - Si l'étape recommande un sous-agent (`subagent_recommendation`), instancier le sous-agent selon l'heuristique prescrite.
   - Soumettre le livrable via `next_step(step_output=...)`.
3. Clôturer avec `end_workflow(...)` une fois l'étape terminale validée.

### 🔹 `/scout` (Reconnaissance, Exploration & Cartographie de Base de Code)
1. `start_workflow(skill_name="scout", initial_context={"scope": "..."})`.
2. Étape 1 : Cartographie architecture et arborescence (outils: `list_dir`, `find_by_name`).
3. Étape 2 : Analyse des dépendances et points d'entrée critiques.
4. Étape 3 : Synthèse de l'état de l'art du repo et rapport structuré.
5. Avancer via `next_step` jusqu'au rapport final.

### 🔹 `/refine` (Spécification Socratique, Ambiguïtés & Analyse Pré-Build)
1. `start_workflow(skill_name="refine")`.
2. Traite les boucles socratiques de clarification avec l'utilisateur (`step_type="interactive"` / `loop_decision`).
3. Mettre à jour les variables de décision avec `next_step(variables={"user_confirmed_choice": ...})`.
4. Continuer jusqu'à l'approbation du plan final.

### 🔹 `/build` (Implémentation, TDD, Validation & Tests Unitaires)
1. `start_workflow(skill_name="build")`.
2. Exécuter la création de code étape par étape en respectant les barrières de tests.
3. Enregistrer les résultats de tests dans `step_output` à chaque appel `next_step`.

### 🔹 `/literature-review` (Revue de Littérature, Analyse Systématique & Synthèse)
1. `start_workflow(skill_name="literature-review", initial_context={"topic": "..."})`.
2. Orchestrer la découverte des sources, l'extraction de métadonnées, l'évaluation critique et la synthèse croisée.
3. Valider chaque étape avec des résumés d'analyse intermédiaires.

---

## 🔒 Règles de Bonne Conduite MCP & Intégrité
- **Stricte Isolation STDIO** : Aucun texte ou log superflu ne doit polluer le flux stdio JSON-RPC (tous les logs internes du serveur sont acheminés vers `stderr`).
- **Gestion Déterministe Mono-Session** : Le serveur gère automatiquement l'unique session active. Aucun argument `session_id` n'est requis ni accepté.
- **Divulgation Progressive** : Toujours laisser `next_step` guider l'étape suivante selon le graphe DAG et les conditions d'exécution.