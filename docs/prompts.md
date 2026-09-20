# DDig — Copilot Prompt Reference

Copilot Chat prompts that automate common DDig workflows.
All prompts live in `.github/prompts/`.

---

## How to Use a Prompt

1. Open Copilot Chat in VS Code (`Cmd+Shift+I`)
2. Type `/` — VS Code will show all available prompts from `.github/prompts/`
3. Select the prompt
4. Supply any required arguments when prompted

---

## Available Prompts

### `fetch-and-score`

**File:** `.github/prompts/fetch-and-score.prompt.md`
**Mode:** `ask` — conversational, guides you step by step. Does not edit files.

**What it does:**
Walks through the full DDig pipeline interactively:
1. Source selection (with auth requirements per source)
2. Credential checks — verifies env vars are set before generating commands
3. Fetch command generation — tailored to the chosen source
4. Stats check — confirms domains landed in the DB
5. Search filter tuning — helps narrow results
6. Export — generates the export command if needed

**When to use it:**
- Running the pipeline for the first time
- Trying a new source you haven't used before
- Tuning search filters for a specific niche or TLD

**How to invoke:**
```
/fetch-and-score
```

The prompt will ask which source to use. To skip that question:
```
/fetch-and-score source_name=dropcatch
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `source_name` | No | Pre-select a source: `dropcatch`, `expireddomains`, `czds`, `name`, `majestic`, `snapnames`, `parkio` |

**Source notes:**
- `majestic` is enrichment-only — the prompt will warn you and suggest running a primary source first
- `czds` prompts you to run `ddig czds-tlds` before fetching to confirm TLD approval
- `name` will note that Playwright re-auth triggers automatically if the session cookie is expired
- `snapnames` fetches both `allexpiring` and `deleting` feeds by default; pass `--feed` to fetch one
- `parkio` fetches all 18 TLDs by default; pass `--tlds io,co` to restrict

---

### `add-source`

**File:** `.github/prompts/add-source.prompt.md`
**Mode:** `agent` — autonomous, creates and edits files directly using tools

**What it does:**
Scaffolds a complete new DDig domain source end-to-end:
1. Reads `dropcatch.py` as the canonical reference implementation
2. Creates `ddig/sources/<name>.py` with correct auth pattern
3. Registers in `ddig/sources/__init__.py`
4. Wires CLI branch into `__main__.py` `fetch()` command
5. Creates `docs/sources/<name>.md`
6. Updates sources table in `README.md`
7. Creates `tests/unit/sources/test_<name>.py`
8. Runs smoke test (`ddig fetch --source <name> --verbose`) and unit tests

**When to use it:**
- Adding support for a new domain registrar or drop service

**How to invoke:**
```
/add-source source_name=godaddy
```

With all arguments:
```
/add-source source_name=godaddy auth_type=apikey description="GoDaddy expiring domains via REST API"
```

**Arguments:**

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `source_name` | ✅ Yes | — | Snake_case name e.g. `godaddy`, `namecheap`, `whoisds` |
| `auth_type` | No | `none` | `none \| apikey \| oauth2 \| cookie \| jwt` |
| `description` | No | — | One-line description of what the source provides |

**What the agent enforces automatically:**
- All credentials via `get_env()` from `ddig.env` — never `os.environ.get()`
- `Domain` construction uses `dataclasses.replace()` — verified against `ddig/models/domain.py`
- Tests patch `ddig.env._cache` directly — not `monkeypatch.setenv` or `os.environ`
- `fetch()` uses `yield` — never buffers all domains in a list
- One shell command per code block

**After the agent finishes:**
Run the checklist at the bottom of the prompt manually to confirm all 12 steps completed. The most commonly missed steps are:
- Diagram updates (`cli-commands.md`, `data-flow.md`, `source-class.md`)
- Adding the source to the Architecture section of `copilot-instructions.md`

---

## Anti-Patterns

| ❌ Don't | ✅ Do instead |
|----------|--------------|
| Run `add-source` in `ask` mode | Use `agent` mode — it needs `create_file`, `insert_edit_into_file`, `run_in_terminal` tools |
| Skip the checklist at the end of `add-source` | Work through all 12 items — diagrams and `copilot-instructions.md` are most often missed |
| Use `fetch-and-score` for `czds` without checking TLD access first | Run `ddig czds-tlds` first — fetching unapproved TLDs silently returns 0 domains |
| Use `fetch-and-score` for `majestic` as a standalone fetch | Run a primary source first (`dropcatch` or `expireddomains`), then enrich with majestic |