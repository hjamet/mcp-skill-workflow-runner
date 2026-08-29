# 🚀 `mcp-skill-workflow-runner`

> **Serveur FastMCP Déterministe pour l'Exécution Progressive de Compétences (Skills) & Workflows Antigravity.**

---

## 📖 Sommaire

1. [Vision & Principes Fondamentaux](#-vision--principes-fondamentaux)
2. [Format Déclaratif YAML (Niveau 1)](#-format-déclaratif-yaml-niveau-1)
3. [Architecture du Moteur](#-architecture-du-moteur)
4. [Outils FastMCP Exposés](#-outils-fastmcp-exposés)
5. [Interface Ligne de Commande (CLI)](#-interface-ligne-de-commande-cli)
6. [Installation & Configuration Antigravity](#-installation--configuration-antigravity)
7. [Politique de Robustesse (Zéro Fallback Silencieux)](#-politique-de-robustesse)

---

## 🎯 Vision & Principes Fondamentaux

`mcp-skill-workflow-runner` applique le principe de **Divulgation Progressive Déterministe (*Deterministic Progressive Disclosure*)** pour les agents intelligents de l'écosystème Antigravity.

Au lieu d'injecter un prompt massif de 1000 lignes contenant toutes les étapes d'un workflow dans le contexte de l'agent :
1. L'agent ne reçoit à chaque instant **que l'enveloppe directive de l'étape active** (titre, instructions spécifiques, contraintes, outils mandatés, transitions possibles).
2. L'agent avance d'étape en étape via l'outil `next_step`.
3. Le moteur FastMCP évalue de façon déterministe les transitions, embranchements conditionnels (DAG) et boucles itératives.
4. L'état complet de la session est sauvegardé de manière atomique en mémoire et sur disque (`<session_id>.json`).

---

## 📜 Format Déclaratif YAML (Niveau 1)

Les workflows sont décrits directement dans le frontmatter YAML des fichiers `SKILL.md` ou `workflow.md` :

```yaml
---
name: work
description: Cycle de travail itératif en 5 étapes
workflow:
  version: "1.0"
  type: "loop"                 # "sequential" | "dag" | "loop"
  initial_step: "step_1_exploration"
  
  context_schema:
    project:
      type: "string"
      required: true
      description: "Nom du projet cible"
    iteration:
      type: "integer"
      default: 1

  steps:
    - id: "step_1_exploration"
      title: "💡 Étape 1 : Exploration & Questions"
      section_matcher: "### 3.1"
      step_type: "standard"
      mandated_tools:
        - "view_file"
        - "recall"
      constraints:
        - "INTERDICTION ABSOLUE de poser une question sans recherche préalable"
      next: "step_2_scouts"

    - id: "step_2_scouts"
      title: "🔭 Étape 2 : Déploiement des Scouts"
      section_matcher: "### 3.2"
      step_type: "subagent_barrier"
      subagent_recommendation:
        type: "research"
        clustering_rule: "1 sous-agent par périmètre orthogonal distinct"
        model: "flash"
      next: "step_3_ask"

    - id: "step_3_ask"
      title: "🗣️ Étape 3 : Questionnement Décisionnel"
      section_matcher: "### 3.3"
      step_type: "interactive"
      next: "step_4_action"

    - id: "step_4_action"
      title: "🚀 Étape 4 : Déploiement des Actions"
      section_matcher: "### 3.4"
      step_type: "subagent_barrier"
      mandated_tools:
        - "write_to_file"
      next: "step_5_loop"

    - id: "step_5_loop"
      title: "🔄 Étape 5 : Relance du Cycle"
      section_matcher: "### 3.5"
      step_type: "loop_decision"
      next: "step_1_exploration"           # Boucle vers l'étape initiale
---

# Instructions Détaillées

### 3.1 Exploration & Questions
Consultez les fichiers locaux et mémoires avant de formuler des hypothèses...

### 3.2 Déploiement des Scouts
Lancez les sous-agents sur les clusters découverts...
```

---

## 🛠️ Outils FastMCP Exposés

Le serveur expose 3 outils MCP stdio déterministes :

### 1. `start_workflow`
Initialise un workflow, valide le graphe DAG, crée une session persistante et renvoie l'enveloppe de l'Étape 1.
- **Paramètres** :
  - `skill_name` *(str, obligatoire)* : Nom du skill (`work`, `scout`) ou chemin de fichier.
  - `restart` *(bool, optionnel)* : Si `True`, réinitialise/remplace toute session active existante. Si `False` et qu'une session existe pour ce workflow, la réutilise.
  - `initial_context` *(dict, optionnel)* : Variables de contexte initiales.
  - `workspace_dir` *(str, optionnel)* : Répertoire racine du workspace local.

### 2. `next_step`
Enregistre le livrable de l'étape courante, met à jour le contexte, résout la prochaine étape via le DAG et retourne la nouvelle enveloppe directive.
- **Paramètres** :
  - `user_response` *(str, optionnel)* : Réponse ou livrable textuel.
  - `step_output` *(str/dict, optionnel)* : Données structurées ou rapport d'étape.
  - `transition_choice` *(str, optionnel)* : Choix explicite de transition pour les embranchements.
  - `variables` *(dict, optionnel)* : Mises à jour des variables de session.

### 3. `end_workflow`
Clôture la session active, calcule les métriques d'exécution (durée, nombre d'étapes, cycles) et produit le rapport d'audit.
- **Paramètres** :
  - `final_summary` *(str, optionnel)* : Résumé de clôture.
  - `status` *(str, défaut: "completed")* : Statut final (`completed`, `aborted`, `paused`).

---

## 💻 Interface Ligne de Commande (CLI)

Le package inclut l'utilitaire `skill-workflow` (propulsé par Click et Rich) :

```bash
# Valider la structure d'un skill (YAML, Markdown, DAG)
skill-workflow validate work
skill-workflow validate path/to/SKILL.md

# Lister tous les workflows disponibles (local + global)
skill-workflow list

# Consulter les sessions en cours et passées
skill-workflow sessions

# Exécuter interactivement un workflow étape par étape
skill-workflow run work

# Lancer le serveur FastMCP en mode stdio
skill-workflow serve
```

---

## 📦 Installation & Configuration Antigravity

### ⚡ Installation Automatisée Tout-en-Un (Recommandé)

Les installateurs automatisés s'occupent de tout : détection de Python 3.10+, création du virtualenv, installation des dépendances en mode éditable, enregistrement dans `~/.gemini/config/mcp_config.json`, déploiement des schémas MCP dans `~/.gemini/antigravity/mcp/skill-workflow-runner/`, et création du wrapper CLI `skill-workflow`.

#### 🪟 Windows (PowerShell)

```powershell
# Exécution locale depuis le dépôt cloné :
powershell -ExecutionPolicy Bypass -File .\install.ps1

# Ou en une ligne directe (curl / irm) :
irm https://raw.githubusercontent.com/UNIL-DESI/mcp-skill-workflow-runner/main/install.ps1 | iex
```

#### 🐧 Linux / macOS (Bash)

```bash
# Exécution locale :
bash install.sh

# Ou en une ligne directe (curl) :
curl -fsSL https://raw.githubusercontent.com/UNIL-DESI/mcp-skill-workflow-runner/main/install.sh | bash
```

### ⚙️ Enregistrement Automatique Antigravity MCP

L'installateur génère et maintient l'entrée dans `~/.gemini/config/mcp_config.json` :

```json
{
  "mcpServers": {
    "skill-workflow-runner": {
      "command": "C:\\Users\\hjamet\\Documents\\code\\mcp-skill-workflow-runner\\venv\\Scripts\\python.exe",
      "args": ["-m", "mcp_skill_workflow_runner.server"],
      "disabled": false,
      "alwaysAllow": []
    }
  }
}
```

---

## 🛡️ Politique de Robustesse

- **Zéro fallback silencieux** : Toute anomalie (YAML syntaxiquement invalide, section Markdown introuvable, transition orpheline, condition non évaluable) déclenche une exception typée explicite (`WorkflowResolutionError`, `WorkflowParseError`, `SectionNotFoundError`, `InvalidDAGStructureError`, `TransitionEvaluationError`, `SessionError`).
- **Zéro pollution stdio** : Tous les logs de diagnostic sont envoyés sur `sys.stderr` pour garantir l'intégrité du protocole JSON-RPC de FastMCP sur `sys.stdout`.
- **Persistance Atomique** : Écriture systématique dans un fichier temporaire `<session_id>.tmp` suivi d'un `os.replace` atomique vers `<session_id>.json`.
