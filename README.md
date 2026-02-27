# ACAP System (Autonomous Coding Agent Prep System)

ACAP lets you point Claude at a requirements document and walk away. It handles the full pipeline: turning your PRD into structured prompt files, detecting your tech stack, and running coding agents that build your app feature by feature across as many sessions as it takes.

## Prerequisites

### 1. Install Claude Code

Pick the method for your platform.

**macOS, Linux, or WSL (recommended, auto-updates):**
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
> Windows also needs [Git for Windows](https://git-scm.com/downloads/win) if you don't have it.

**Homebrew (macOS/Linux):**
```bash
brew install --cask claude-code
```
Homebrew won't auto-update. Run `brew upgrade claude-code` now and then to stay current.

**WinGet (Windows):**
```powershell
winget install Anthropic.ClaudeCode
```
WinGet won't auto-update. Run `winget upgrade Anthropic.ClaudeCode` to get the latest.

**VS Code or Cursor:**
Install the [Claude Code extension](https://marketplace.visualstudio.com/items?itemName=anthropic.claude-code) from the marketplace, or just search "Claude Code" in the Extensions panel (`Cmd+Shift+X` on Mac, `Ctrl+Shift+X` on Windows/Linux).

**JetBrains (IntelliJ, PyCharm, WebStorm, etc.):**
Install the [Claude Code plugin](https://plugins.jetbrains.com/plugin/27310-claude-code-beta-) from the JetBrains Marketplace, then restart your IDE.

Check it worked:
```bash
claude --version
```

### 2. Log in

Run this once. Your credentials get stored and all ACAP scripts will use them automatically.
```bash
claude login
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

---

## Recommended Plugins

These plugins are optional but significantly boost what the coding agents can do — enabling
systematic workflows, specialist subagents, and parallel execution across multiple context windows.

### Superpowers

Superpowers gives the coding agents structured workflows for planning, TDD, debugging, code
review, and subagent-driven development. It is installed as a slash command **inside** a Claude
Code session (not in your terminal):

```
# Inside any Claude Code session (start one with: claude):
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
```

Takes effect in new sessions after install.

### Awesome Claude Code Subagents

127+ specialist agents (TypeScript, Python, Rust, Go, React, backend, frontend, etc.) that the
coding agents can delegate to automatically. Install via your terminal:

```bash
# Language specialists (TypeScript, Python, Rust, Go, React, etc.)
claude plugin install voltagent-lang

# Infrastructure & DevOps (Docker, Kubernetes, CI/CD, cloud, etc.)
claude plugin install voltagent-infra
```

Install both for full coverage. Once installed, the coding agents will automatically delegate to
the right specialist — e.g. a TypeScript project will use the `typescript-pro` subagent for
type-heavy work.

### Agent Teams (Experimental)

When enabled, the coding agent can spin up a lead plus multiple specialist teammates working in
parallel (frontend dev + backend dev + QA), each in their own context window. Token cost is
higher but wall-clock time drops significantly for large features.

To enable, set this environment variable before running ACAP:

```bash
# Add to your shell profile or set before running ACAP:
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
```

---

## Quick Start

**Step 1: Generate your `prompts/` files from a PRD or product brief**

```bash
# Interactive: paste your requirements and answer a few questions
python acaps.py --prompt

# Or point it at a file
python acaps.py --prompt --prompt-files ./my_prd.txt
```

**Step 2: Detect your tech stack and write the config**

```bash
python acaps.py --configure --project-dir ./my_project
```

**Step 3: Run the coding agents**

```bash
python acaps.py --project-dir ./my_project
```

You can also do all three steps in one go:
```bash
python acaps.py --prompt --prompt-files ./my_prd.txt \
    --configure --project-dir ./my_project
```

---

## How It Works

### Prompt Wizard (`--prompt`)

This is the starting point. Give it your requirements document and it spits out the three files the coding agents need. Here is what happens under the hood:

1. **Collect** - reads your file(s) or lets you paste text directly in the terminal
2. **Analyze** - a quick AI pass reads your requirements and comes up with 3 to 7 clarifying questions about anything that is vague or missing
3. **Q&A** - you answer the questions in the terminal (just hit Enter to skip any)
4. **Generate** - a second AI pass writes all three files based on your answers
5. **Write** - saves `prompts/app_spec.txt`, `prompts/initializer_prompt.md`, and `prompts/coding_prompt.md`

If you want to redo this and replace files that already exist, add `--prompt-overwrite`.

### Stack Detection (`--configure`)

Reads your `prompts/` files and figures out your tech stack automatically, then writes a `.env` config file so you do not have to set anything up by hand.

What it writes to `.env`:
- `FRAMEWORK` - e.g. `laravel`, `django`, `react`, `generic`
- `PACKAGE_MANAGER` - e.g. `npm`, `pip`, `composer+npm`
- `DEV_SERVER_CMD` and `DEV_SERVER_PORT` - how to start the app
- `AGENT_SYSTEM_PROMPT` - a custom system prompt tuned for your stack

Run `--configure` again any time you edit `prompts/` to refresh the config.

### The Two Agents

**Agent 1 - Initializer (runs once):** Reads `app_spec.txt`, writes `feature_list.json` with 200 end-to-end test cases, sets up the project folders, and makes the first git commit.

**Agent 2 - Coding Agent (runs every session after that):** Picks up from where the last session ended, implements one feature at a time using browser automation to verify it works, and marks it as passing in `feature_list.json`.

### Sessions

- Every session starts with a fresh context window
- Progress is tracked in `feature_list.json` and git commits so nothing gets lost
- The system automatically starts the next session after a 3 second pause
- Hit `Ctrl+C` to stop at any time. Run the same command again to pick back up.

---

## Timing

> **Heads up: this runs for a long time.**

- **First session:** Writing 200 test cases takes a few minutes and may look like it froze. It has not. Watch for `[Tool: ...]` lines to confirm it is running.
- **Each coding session:** Roughly 5 to 15 minutes per feature depending on complexity.
- **Full app:** Completing all 200 features takes many hours across many sessions.

If you just want to try it out quickly, open `prompts/initializer_prompt.md` and change "200" to something like 20 or 50.

---

## Security

The agents only have access to what they need (see `security.py` and `client.py`):

1. **Sandbox** - bash commands run in an isolated environment at the OS level
2. **Filesystem** - file operations are locked to the project directory only
3. **Command allowlist** - only specific commands are allowed to run:
   - Browsing files: `ls`, `cat`, `head`, `tail`, `wc`, `grep`
   - Node.js: `npm`, `node`
   - Git: `git`
   - Process management: `ps`, `lsof`, `sleep`, `pkill` (dev processes only)

Anything not on the list gets blocked automatically.

---

## Project Structure

```
acap/
├── acaps.py  # Main entry point
├── agent.py                  # Agent session logic
├── client.py                 # Claude SDK client setup
├── configure.py              # Stack detection and .env writing
├── prompter.py               # Prompt wizard (turns your PRD into prompts/)
├── security.py               # Command allowlist and validation
├── progress.py               # Progress tracking
├── prompts.py                # Prompt file loading
├── prompts/
│   ├── app_spec.txt          # Your app specification (XML)
│   ├── initializer_prompt.md # Instructions for the first agent session
│   └── coding_prompt.md      # Instructions for all sessions after that
└── requirements.txt          # Python dependencies
```

## Generated Project Structure

Once it starts building, your project folder will look like this:

```
my_project/
├── feature_list.json         # The master list of test cases
├── app_spec.txt              # Copy of your spec
├── init.sh                   # Script to start the dev environment
├── claude-progress.txt       # Notes from previous sessions
├── .claude_settings.json     # Security settings
└── [your app files]
```

---

## Running the App

Once the agents have built something (or you want to check on progress):

```bash
cd generations/my_project

# Use the setup script the agent wrote
./init.sh

# Or start it manually (most Node.js apps):
npm install
npm run dev
```

It will usually be at `http://localhost:3000`. Check `init.sh` or the agent output for the exact URL.

---

## Options

| Option | What it does | Default |
|--------|-------------|---------|
| `--project-dir` | Where to put the project | `./autonomous_demo_project` |
| `--max-iterations` | Cap on agent sessions | None |
| `--model` | Which Claude model to use | from `.env` or `claude-sonnet-4-6` |
| `--configure` | Detect stack and write `.env` | off |
| `--configure-model` | Model for stack detection | from `.env` or haiku |
| `--prompt` | Run the prompt wizard | off |
| `--prompt-files` | File(s) to feed the wizard | interactive |
| `--prompt-overwrite` | Overwrite existing prompt files | off |

---

## Customization

### Swap out the app

Run the wizard again with new requirements:
```bash
python acaps.py --prompt --prompt-files ./new_prd.txt --prompt-overwrite
```

Or just edit `prompts/app_spec.txt` directly.

### Fewer features for faster runs

Edit `prompts/initializer_prompt.md` and change "200 features" to whatever number you want.

### Add commands to the allowlist

Edit `ALLOWED_COMMANDS` in `security.py`.

---

## Troubleshooting

**It looks frozen on the first run**
It is not frozen. Writing 200 test cases just takes a while. Look for `[Tool: ...]` lines in the output to confirm it is still working.

**"Command blocked by security hook"**
The agent tried to run something that is not on the allowlist. That is the security system doing its job. If you need that command, add it to `ALLOWED_COMMANDS` in `security.py`.

**"Not authenticated"**
Run `claude login`. You can also set `ANTHROPIC_API_KEY` in your environment if you prefer that route.

---

## License

Internal Anthropic use.
