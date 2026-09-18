# api-diver

Maps Swagger/OpenAPI specs into **agent skills**. You just give it a URL (a
JSON spec or a swagger-ui page); api-diver discovers on its own the specs
behind it — multiple domains, routes, parameters and payloads — then generates
a standard **Agent Skills** skill installable for OpenCode, Mistral Vibe,
Claude Code, Codex, GitHub Copilot (and any compatible agent via `.agents/`).

## Installation

```bash
uv tool install .        # or: pipx install .
```

## Quick start

```bash
# 1. create a knowledge base (once)
api-diver init my-apis
cd my-apis

# 2. add swagger URLs, whenever you want
api-diver add https://api.example.com/swagger/index.html
api-diver add https://petstore.swagger.io/v2/swagger.json --name petstore

# 3. refresh the routes (one command)
api-diver update            # every API
api-diver update my-api     # a single one

# 4. generate / install the skill
api-diver build --install                  # .agents/skills/ (OpenCode + Vibe + Codex)
api-diver build --target claude --install  # .claude/skills/ (Claude Code)
api-diver build --target copilot --install # .github/skills/ (Copilot)
api-diver build --target vibe --install --global
```

The skill is always named `api-diver` (folder `api-diver/`, command
`/api-diver` — identical in every project). Override with
`init --skill-name` or `build --name`.

## What `add` does (automatic discovery)

1. Fetches the URL; if it is already a swagger.json/openapi.json → direct spec.
2. If it is a **swagger-ui HTML page**: extracts the referenced specs (embedded
   `JSON.parse` config, `urls` arrays, `configUrl`, `data-spec-url`, then
   fallbacks `swagger.json`, `v1/swagger.json`...).
3. Every discovered spec is crawled (the multi-document Swashbuckle case —
   "Service A", "Service B"... — becomes **one API with a group per spec**),
   then everything is merged.
4. **Multiple domains** are supported: OpenAPI 3 `servers[]` (with `{env}`
   variables resolved), Swagger 2 `schemes × host + basePath`.

## Workspace (knowledge base)

```
my-apis/
├── apidiver.json           # registry: sources, spec URLs, auth refs
├── specs/<api>/
│   ├── raw/*.json          # downloaded raw specs (+ .prev: history)
│   └── normalized.json     # merged model (+ .prev)
└── api-diver/              # generated skill (build / update --skill)
```

- `api-diver list` / `info <api>` / `diff <api>`: explore the workspace.
- `api-diver remove <api>`: remove an API.

## Generated skill

```
api-diver/
├── SKILL.md                # index + navigation guide (progressive disclosure)
└── apis/<api>/
    ├── overview.md         # domains (base URLs), groups, auth, tags
    └── routes/
        ├── _index.md       # METHOD path → file
        └── <tag>.md        # route sheets: params, payload + JSON example,
                            # detailed responses, curl example
```

Curl examples use `$MY_API_TOKEN`-style placeholders: no secret is ever
written to the workspace or the skill.

## Install targets (`build --target`)

| Target | Project dir (`--install`) | Global dir (`--install --global`) | Agent |
|---|---|---|---|
| `agents` (default) | `.agents/skills/` | `~/.agents/skills/` | OpenCode, Mistral Vibe, any compatible agent |
| `opencode` | `.opencode/skills/` | `~/.config/opencode/skills/` | OpenCode |
| `vibe` | `.vibe/skills/` | `~/.vibe/skills/` | Mistral Vibe |
| `claude` | `.claude/skills/` | `~/.claude/skills/` | Claude Code |
| `codex` | `.agents/skills/` | `~/.agents/skills/` | Codex (≥ 0.95: reads the standard `.agents` folder) |
| `copilot` | `.github/skills/` | `~/.copilot/skills/` | GitHub Copilot (VS Code, CLI, coding agent) |

## Authenticating protected sources

```bash
# value read from the environment on each fetch (recommended, stored as a ref)
api-diver add https://.../swagger.json --header "Authorization: {\$MY_TOKEN}"

# or globally
export API_DIVER_HEADERS='{"X-Api-Key": "{$MY_KEY}"}'
```

A raw value (`--header "Authorization: Bearer xyz"`) is used for the current
fetch only and is **never stored**.

## Commands

| Command | Purpose |
|---|---|
| `init [path]` | Create the workspace |
| `add <url> [--name n]` | Crawl + add a source (auto discovery) |
| `update [name] [--skill]` | Re-crawl and refresh routes (+ diff summary) |
| `list` / `info <name>` | Explore the workspace |
| `diff <name>` | Route changes since the previous version |
| `remove <name>` | Remove an API |
| `build [--target agents\|opencode\|vibe\|claude\|codex\|copilot] [--install] [--global]` | Generate/install the skill |

`update --skill` chains the update with a full regeneration of the skill,
automatically reinstalled to the agents detected in the project
(`.agents/`, `.claude/`, `.opencode/`, `.vibe/`, `.github/skills` or
`.github/copilot-instructions.md`). If no agent is detected, nothing is
installed — use `build --install --target <target>`. Both `update --skill`
and `build --install` also clean up the legacy naming: a skill folder (or
agent install) still named after the project folder is renamed/removed in
favor of `api-diver`.

## Development

```bash
uv venv && uv pip install -e . pytest
uv run pytest
```
