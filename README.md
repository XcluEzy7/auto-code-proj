# ACAP System — Autonomous Coding Agent Prep System

ACAP is a production harness for long-running autonomous coding with the Claude Agent SDK. It implements a two-agent pattern (initializer + coding agent) that builds complete applications over many sessions, driven entirely by your requirements document.

## Prerequisites

### 1. Install Claude Code

Choose the method that suits your platform.

**macOS / Linux / WSL (Recommended — auto-updates):**
```bash
curl -fsSL https://claude.ai/install.sh | bash
```

**Windows PowerShell (auto-updates):**
```powershell
irm https://claude.ai/install.ps1 | iex
```

**Windows CMD:**
```batch
curl -fsSL https://claude.ai/install.cmd -o install.cmd && install.cmd && del install.cmd
```
> Windows requires [Git for Windows](https://git-scm.com/downloads/win).

**Homebrew (macOS/Linux):**
```bash
brew install --cask claude-code
# Run `brew upgrade claude-code` periodically — Homebrew does not auto-update.
```

**WinGet (Windows):**
```powershell
winget install Anthropic.ClaudeCode
# Run `winget upgrade Anthropic.ClaudeCode` periodically — WinGet does not auto-update.
```

**VS Code / Cursor:**
Install the [Claude Code extension](https://marketplace.visualstudio.com/items?itemName=anthropic.claude-code) from the marketplace, or search for "Claude Code" in the Extensions view (`Cmd+Shift+X` / `Ctrl+Shift+X`).

**JetBrains IDEs (IntelliJ, PyCharm, WebStorm, etc.):**
Install the [Claude Code plugin](https://plugins.jetbrains.com/plugin/27310-claude-code-beta-) from the JetBrains Marketplace, then restart your IDE.

Verify your installation:
```bash
claude --version
```

### 2. Authenticate

Log in once — credentials are stored and used by all ACAP scripts automatically:
```bash
claude login
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

---

## Quick Start

**Step 1 — Generate your `prompts/` files from a PRD or product brief:**

```bash
# Interactive — paste your requirements, answer a few questions:
python autonomous_agent_demo.py --prompt

# From a file:
python autonomous_agent_demo.py --prompt --prompt-files ./my_prd.txt
```

**Step 2 — Detect your tech stack and write `.env`:**

```bash
python autonomous_agent_demo.py --configure --project-dir ./my_project
```

**Step 3 — Run the coding agents:**

```bash
python autonomous_agent_demo.py --project-dir ./my_project
```

Or run the full pipeline in one command:
```bash
python autonomous_agent_demo.py --prompt --prompt-files ./my_prd.txt \
    --configure --project-dir ./my_project
```

---

## How It Works

### Prompt Wizard (`--prompt`)

Before any coding begins, the wizard turns your raw requirements into the three structured files the agents need:

1. **Collect** — reads from `--prompt-files` or accepts pasted text interactively
2. **Analyze** — a fast AI analysis identifies gaps and generates 3–7 clarifying questions
3. **Q&A** — you answer the questions in the terminal (Enter to skip any)
4. **Generate** — a capable AI session produces all three files following the harness templates
5. **Write** — `prompts/app_spec.txt`, `prompts/initializer_prompt.md`, `prompts/coding_prompt.md` are written to disk

Use `--prompt-overwrite` to replace existing files.

### Stack Detection (`--configure`)

Reads your `prompts/` files and auto-detects the tech stack to write a `.env` configuration file — so you don't have to manually figure out the dev server command, port, package manager, or agent system prompt.

Key values written to `.env`:
- `FRAMEWORK` — e.g. `laravel`, `django`, `react`, `generic`
- `PACKAGE_MANAGER` — e.g. `npm`, `pip`, `composer+npm`
- `DEV_SERVER_CMD` / `DEV_SERVER_PORT` — how to start the app
- `AGENT_SYSTEM_PROMPT` — a stack-tailored system prompt for the coding agents

Run `--configure` again any time you update `prompts/` to regenerate `.env`.

### Two-Agent Pattern

1. **Initializer Agent (Session 1):** Reads `app_spec.txt`, creates `feature_list.json` with 200 end-to-end test cases, sets up the project structure, and initializes git.

2. **Coding Agent (Sessions 2+):** Picks up where the previous session left off, implements features one by one through the UI using browser automation, and marks them as passing in `feature_list.json`.

### Session Management

- Each session runs with a fresh context window
- Progress is persisted via `feature_list.json` and git commits
- The agent auto-continues between sessions (3 second delay)
- Press `Ctrl+C` to pause; run the same command to resume

---

## Important Timing Expectations

> **Note: This system runs long tasks.**

- **First session (initialization):** Generating `feature_list.json` with 200 test cases takes several minutes and may appear to hang — this is normal.
- **Subsequent sessions:** Each coding iteration takes **5–15 minutes** depending on complexity.
- **Full application:** Building all 200 features typically requires **many hours** across multiple sessions.

**Tip:** Edit `prompts/initializer_prompt.md` and reduce the feature count (e.g. to 20–50) for faster runs.

---

## Security Model

Defense-in-depth approach (see `security.py` and `client.py`):

1. **OS-level Sandbox:** Bash commands run in an isolated environment
2. **Filesystem Restrictions:** File operations restricted to the project directory only
3. **Bash Allowlist:** Only specific commands are permitted:
   - File inspection: `ls`, `cat`, `head`, `tail`, `wc`, `grep`
   - Node.js: `npm`, `node`
   - Version control: `git`
   - Process management: `ps`, `lsof`, `sleep`, `pkill` (dev processes only)

Commands not in the allowlist are blocked by the security hook.

---

## Project Structure

```
acap/
├── autonomous_agent_demo.py  # Main entry point
├── agent.py                  # Agent session logic
├── client.py                 # Claude SDK client configuration
├── configure.py              # Stack detection and .env generation
├── prompter.py               # Prompt wizard (generates prompts/ from PRD)
├── security.py               # Bash command allowlist and validation
├── progress.py               # Progress tracking utilities
├── prompts.py                # Prompt loading utilities
├── prompts/
│   ├── app_spec.txt          # Application specification (XML)
│   ├── initializer_prompt.md # First session prompt
│   └── coding_prompt.md      # Continuation session prompt
└── requirements.txt          # Python dependencies
```

## Generated Project Structure

After running, your project directory will contain:

```
my_project/
├── feature_list.json         # Test cases (source of truth)
├── app_spec.txt              # Copied specification
├── init.sh                   # Environment setup script
├── claude-progress.txt       # Session progress notes
├── .claude_settings.json     # Security settings
└── [application files]       # Generated application code
```

---

## Running the Generated Application

```bash
cd generations/my_project

# Run the setup script created by the agent
./init.sh

# Or manually (typical for Node.js apps):
npm install
npm run dev
```

The application will typically be available at `http://localhost:3000` (check the agent's output or `init.sh` for the exact URL).

---

## Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--project-dir` | Directory for the project | `./autonomous_demo_project` |
| `--max-iterations` | Max agent iterations | Unlimited |
| `--model` | Claude model to use | from `.env` or `claude-sonnet-4-6` |
| `--configure` | Detect tech stack and write `.env` | — |
| `--configure-model` | Model for the configure agent | from `.env` or haiku |
| `--prompt` | Launch prompt wizard to generate `prompts/` files | — |
| `--prompt-files` | Source file(s) for the wizard (requires `--prompt`) | interactive |
| `--prompt-overwrite` | Overwrite existing `prompts/` files | — |

---

## Customization

### Changing the Application

Use the prompt wizard with a new requirements document:
```bash
python autonomous_agent_demo.py --prompt --prompt-files ./new_prd.txt --prompt-overwrite
```

Or edit `prompts/app_spec.txt` directly.

### Adjusting Feature Count

Edit `prompts/initializer_prompt.md` and change the "200 features" requirement to a smaller number for faster runs.

### Modifying Allowed Commands

Edit `security.py` to add or remove commands from `ALLOWED_COMMANDS`.

---

## Troubleshooting

**"Appears to hang on first run"**
Normal. The initializer agent is generating 200 detailed test cases. Watch for `[Tool: ...]` output to confirm it is working.

**"Command blocked by security hook"**
The agent tried to run a command not in the allowlist. This is the security system working as intended. Add the command to `ALLOWED_COMMANDS` in `security.py` if needed.

**"Not authenticated"**
Run `claude login` to authenticate via the Claude Code CLI. Alternatively, set `ANTHROPIC_API_KEY` in your environment.

---

## License

Internal Anthropic use.
