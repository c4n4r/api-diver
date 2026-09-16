# api-diver

Cartographie des swaggers/OpenAPI en **skills agents**. Tu donnes juste une URL
(une spec JSON ou une page swagger-ui), api-diver découvre tout seul les specs
derrière, les multi-domaines, les routes, leurs paramètres et payloads — puis
génère un skill au format standard **Agent Skills** installable pour OpenCode,
Mistral Vibe, Claude Code, Codex, GitHub Copilot (et tout agent compatible via
`.agents/`).

## Installation

```bash
uv tool install .        # ou : pipx install .
```

## Démarrage rapide

```bash
# 1. créer une base de connaissance (une seule fois)
api-diver init apis-perso
cd apis-perso

# 2. ajouter des URLs de swagger, quand tu veux
api-diver add https://vnext.sosoxygene.com/api-stock/swagger/index.html
api-diver add https://petstore.swagger.io/v2/swagger.json --name petstore

# 3. mettre à jour les routes (une commande)
api-diver update            # toutes les APIs
api-diver update api-stock  # une seule

# 4. générer / installer le skill
api-diver build --install                  # .agents/skills/ (OpenCode + Vibe + Codex)
api-diver build --target claude --install  # .claude/skills/ (Claude Code)
api-diver build --target copilot --install # .github/skills/ (Copilot)
api-diver build --target vibe --install --global
```

## Ce que fait `add` (découverte automatique)

1. Récupère l'URL ; si c'est déjà un swagger.json/openapi.json → spec directe.
2. Si c'est une **page swagger-ui HTML** : extrait les specs référencées
   (config `JSON.parse` embarquée, tableaux `urls`, `configUrl`,
   `data-spec-url`, puis fallbacks `swagger.json`, `v1/swagger.json`...).
3. Chaque spec découverte est crawlée (le cas Swashbuckle multi-docs —
   « Agency Tanks », « Articles »... — devient **une API avec un groupe par
   spec**), puis tout est fusionné.
4. Les **multi-domaines** sont gérés : `servers[]` OpenAPI 3 (avec variables
   `{env}` résolues), `schemes × host + basePath` Swagger 2.

## Workspace (base de connaissance)

```
apis-perso/
├── apidiver.json           # registry : sources, URLs des specs, refs d'auth
└── specs/<api>/
    ├── raw/*.json          # specs brutes téléchargées (+ .prev : historique)
    └── normalized.json     # modèle fusionné (+ .prev)
```

- `api-diver list` / `info <api>` / `diff <api>` : explorer le workspace.
- `api-diver remove <api>` : retirer une API.

## Skill généré

```
<skill>/
├── SKILL.md                # index + guide de navigation (progressive disclosure)
└── apis/<api>/
    ├── overview.md         # domaines (base URLs), groupes, auth, tags
    └── routes/
        ├── _index.md       # METHOD chemin → fichier
        └── <tag>.md        # fiches : params, payload + exemple JSON,
                            # réponses détaillées, exemple curl
```

Les exemples curl utilisent des placeholders `$NOM_API_TOKEN`-style : aucun
secret n'est jamais écrit dans le workspace ni le skill.

## Cibles d'installation (`build --target`)

| Cible | Dossier projet (`--install`) | Dossier global (`--install --global`) | Agent |
|---|---|---|---|
| `agents` (défaut) | `.agents/skills/` | `~/.agents/skills/` | OpenCode, Mistral Vibe, tout agent compatible |
| `opencode` | `.opencode/skills/` | `~/.config/opencode/skills/` | OpenCode |
| `vibe` | `.vibe/skills/` | `~/.vibe/skills/` | Mistral Vibe |
| `claude` | `.claude/skills/` | `~/.claude/skills/` | Claude Code |
| `codex` | `.agents/skills/` | `~/.agents/skills/` | Codex (≥ 0.95 : lit le dossier standard `.agents`) |
| `copilot` | `.github/skills/` | `~/.copilot/skills/` | GitHub Copilot (VS Code, CLI, coding agent) |

## Authentification des sources protégées

```bash
# valeur lue dans l'environnement à chaque fetch (recommandé, persisté en ref)
api-diver add https://.../swagger.json --header "Authorization: {\$MY_TOKEN}"

# ou globalement
export API_DIVER_HEADERS='{"X-Api-Key": "{$MY_KEY}"}'
```

Une valeur brute (`--header "Authorization: Bearer xyz"`) sert au fetch du
moment et n'est **jamais stockée**.

## Commandes

| Commande | Rôle |
|---|---|
| `init [path]` | Créer le workspace |
| `add <url> [--name n]` | Crawler + ajouter une source (découverte auto) |
| `update [name] [--skill]` | Re-crawler et rafraîchir les routes (+ résumé diff) |
| `list` / `info <name>` | Explorer le workspace |
| `diff <name>` | Changements de routes depuis la version précédente |
| `remove <name>` | Supprimer une API |
| `build [--target agents\|opencode\|vibe\|claude\|codex\|copilot] [--install] [--global]` | Générer/installer le skill |

`update --skill` enchaîne la mise à jour avec la régénération du skill complet,
réinstallé automatiquement vers les agents détectés dans le projet
(`.agents/`, `.claude/`, `.opencode/`, `.vibe/`, `.github/skills` ou
`.github/copilot-instructions.md`). Sans agent détecté, rien n'est installé —
utilise `build --install --target <cible>`.

## Développement

```bash
uv venv && uv pip install -e . pytest
uv run pytest
```
