"""
Prompt Wizard
=============

Interactive wizard that accepts raw requirements (pasted text or file paths)
and generates all three prompt files needed by the agent harness:
  - prompts/app_spec.txt
  - prompts/initializer_prompt.md
  - prompts/coding_prompt.md

Usage (from acaps.py):
    from prompter import run_prompter
    await run_prompter(prompt_files=["prd.txt"], overwrite=False)

Or standalone:
    python prompter.py
"""

import asyncio
from pathlib import Path
from typing import Callable

from config import get_config
from configure import extract_json_from_text
from provider_cli import provider_default_model, run_prompt_task


DEFAULT_ANALYSIS_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_GENERATION_MODEL = "claude-sonnet-4-6"
GENERATION_REQUIRED_KEYS = {"app_spec", "initializer_prompt", "coding_prompt"}
StatusCallback = Callable[[str, str], None]
StreamCallback = Callable[[str, str], None]
AUTONOMY_OVERRIDE_BLOCK = """\
## Autonomous Execution Contract

- Run in fully autonomous mode without pausing for human confirmation.
- If a workflow suggests brainstorming/approval checkpoints, continue with bounded assumptions.
- Record key assumptions in output and keep moving.
- Never block waiting for user input once execution has started.
"""

ANALYSIS_SYSTEM_PROMPT = """\
You are a technical architect analyzing product requirements documents.

When given a user's requirements document, you will:
1. Summarize what will be built in 1-2 sentences
2. Identify 3-7 specific questions to clarify before generating the full specification

Focus questions on missing specifics such as:
- Technology stack choices (if not specified)
- Authentication/authorization requirements
- Deployment target (local, cloud, Docker, etc.)
- External integrations or APIs needed
- User audience type and expected scale
- Data persistence requirements
- Any ambiguous or conflicting requirements

If the user does not specify a stack or package manager, default to a Turborepo
monorepo using Bun as the primary package manager with pnpm as a fallback.
Do not ask a question about package manager or monorepo tooling unless the user
explicitly indicates a different preference.

Output ONLY a valid JSON object with these exact keys:
- analysis: string (1-2 sentence summary of what will be built)
- questions: array of objects, each with:
  - question: string (the specific clarifying question)
  - why: string (why this information is needed, e.g. "needed for choosing the right framework")

Output ONLY the JSON object, starting with { and ending with }. No other text.
"""

GENERATION_SYSTEM_PROMPT = """\
You are a technical writer creating structured prompt files for an autonomous AI coding agent system.

The system requires three files:
1. app_spec.txt — A detailed XML project specification document
2. initializer_prompt.md — Instructions for the initializer agent (Session 1 of many)
3. coding_prompt.md — Instructions for ongoing coding agents (Sessions 2+)

You will receive:
- A user's requirements document
- Clarifying Q&A answers
- Template examples showing the exact format each file must follow

Generate all three files following the exact structure of the provided templates.
Customize all content (project name, features, tech stack, database schema, API endpoints,
UI layout, design system, implementation steps) to match the user's specific requirements.

Default choices (unless the user specifies otherwise):
- Use a Turborepo monorepo layout with `apps/` and `packages/`
- Use Bun as the primary package manager and document a pnpm fallback
- Prefer `bunx turbo` for running Turborepo commands

Output ONLY a valid JSON object with these exact keys:
- app_spec: string (full XML project specification following <project_specification> format)
- initializer_prompt: string (full markdown instructions for initializer agent)
- coding_prompt: string (full markdown instructions for coding agent)

Output ONLY the JSON object, starting with { and ending with }. No other text.
"""


def collect_source_documents(prompt_files: list[str] | None) -> str:
    """
    Phase 1: Collect source documents from files or interactive terminal input.

    Args:
        prompt_files: List of file paths to read, or None for interactive input.

    Returns:
        Concatenated source content string.

    Raises:
        FileNotFoundError: If a specified file does not exist.
        ValueError: If the resulting content is empty.
    """
    if prompt_files:
        parts = []
        for file_path in prompt_files:
            path = Path(file_path)
            if not path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")
            content = path.read_text(encoding="utf-8")
            parts.append(f"=== {path.name} ===\n{content}")
        result = "\n\n".join(parts)
    else:
        print("\n" + "=" * 60)
        print("PROMPT WIZARD — Collect Requirements")
        print("=" * 60)
        print("\nPaste your requirements document below.")
        print("Type '---' on its own line when done (or press Ctrl+D for EOF):\n")

        lines = []
        try:
            while True:
                line = input()
                if line.strip() == "---":
                    break
                lines.append(line)
        except EOFError:
            pass

        result = "\n".join(lines).strip()

    if not result.strip():
        raise ValueError(
            "No requirements provided. Please provide a requirements document."
        )

    return result


async def run_analysis_session(
    content: str,
    model: str,
    provider_id: str,
    status_callback: StatusCallback | None = None,
    stream_callback: StreamCallback | None = None,
) -> dict:
    """
    Phase 2: AI analysis session — understand requirements, generate clarifying questions.

    Args:
        content: Raw requirements content from Phase 1.
        model: Model to use (defaults to haiku for speed/cost).

    Returns:
        Dict with keys: analysis (str), questions (list of {question, why} dicts).
    """
    print("\n" + "=" * 60)
    print("PHASE 2 — Analyzing Requirements")
    print("=" * 60)
    print(f"Model: {model}")
    print("Identifying gaps and generating clarifying questions...\n")
    if status_callback:
        status_callback("analyze", "Identifying gaps and generating clarifying questions")

    query = (
        "Please analyze the following requirements document and generate clarifying questions.\n\n"
        f"REQUIREMENTS DOCUMENT:\n{content}\n\n"
        "Output ONLY a valid JSON object as described in your instructions."
    )

    cfg = get_config()
    result = run_prompt_task(
        provider_id=provider_id,
        model=model,
        system_prompt=ANALYSIS_SYSTEM_PROMPT,
        prompt=query,
        cwd=Path.cwd(),
        cfg=cfg,
        allowed_tools="Edit,Bash,Task",
        stream_callback=stream_callback,
    )

    if result.returncode != 0:
        error_msg = result.stderr[:500] if result.stderr else "(no stderr)"
        raise RuntimeError(f"Analysis failed: {error_msg}")

    result_data = extract_json_from_text(result.stdout)

    print(f"Analysis: {result_data.get('analysis', '?')}")
    print(f"Questions identified: {len(result_data.get('questions', []))}\n")

    return result_data


def conduct_qa(questions: list[dict], answers: list[str] | None = None) -> list[dict]:
    """
    Phase 3: Interactive Q&A — ask each question and collect user answers.

    Args:
        questions: List of {question, why} dicts from Phase 2.

    Returns:
        List of {question, answer} dicts (answer may be empty if user skipped).
    """
    print("\n" + "=" * 60)
    print("PHASE 3 — Clarifying Questions")
    print("=" * 60)
    print("Please answer the following questions (press Enter to skip):\n")

    qa_pairs = []
    provided_answers = answers or []
    for i, q in enumerate(questions, 1):
        question = q.get("question", "")
        why = q.get("why", "")

        print(f"Q{i}: {question}")
        if why:
            print(f"     (Why: {why})")

        if i - 1 < len(provided_answers):
            answer = provided_answers[i - 1].strip()
            print(f"A: {answer}")
        else:
            try:
                answer = input("A: ").strip()
            except EOFError:
                answer = ""

        qa_pairs.append({"question": question, "answer": answer})
        print()

    return qa_pairs


def _load_template(filename: str) -> str:
    """Load a template file from prompts/, preferring *-template variants."""
    prompts_dir = Path(__file__).parent / "prompts"
    preferred = prompts_dir / filename
    if preferred.exists():
        return preferred.read_text(encoding="utf-8")

    if "." in filename:
        base, ext = filename.rsplit(".", 1)
        template_variant = prompts_dir / f"{base}-template.{ext}"
        if template_variant.exists():
            return template_variant.read_text(encoding="utf-8")
    return ""


def apply_autonomy_override(text: str, enabled: bool = True) -> str:
    """Append autonomy constraints once to prevent blocking workflow prompts."""
    if not enabled:
        return text
    marker = "## Autonomous Execution Contract"
    if marker in text:
        return text
    return text.rstrip() + "\n\n" + AUTONOMY_OVERRIDE_BLOCK.strip() + "\n"


async def run_generation_session(
    content: str,
    qa_pairs: list[dict],
    model: str,
    provider_id: str,
    status_callback: StatusCallback | None = None,
    stream_callback: StreamCallback | None = None,
) -> dict:
    """
    Phase 4: AI generation session — produce all three prompt files.

    Args:
        content: Original requirements content from Phase 1.
        qa_pairs: List of {question, answer} dicts from Phase 3.
        model: Model to use for generation (defaults to sonnet).

    Returns:
        Dict with keys: app_spec, initializer_prompt, coding_prompt.
    """
    print("\n" + "=" * 60)
    print("PHASE 4 — Generating Prompt Files")
    print("=" * 60)
    print(f"Model: {model}")
    print("Generating app_spec.txt, initializer_prompt.md, coding_prompt.md...\n")
    if status_callback:
        status_callback("generate", "Generating app_spec.txt, initializer_prompt.md, coding_prompt.md")

    # Load template examples from the existing prompts/ directory
    app_spec_template = _load_template("app_spec-template.txt")
    initializer_template = _load_template("initializer_prompt-template.md")
    coding_template = _load_template("coding_prompt-template.md")

    # Build Q&A section (only include answered questions)
    qa_section = ""
    if qa_pairs:
        answered = [p for p in qa_pairs if p.get("answer")]
        if answered:
            qa_lines = [
                f"Q: {p['question']}\nA: {p['answer']}" for p in answered
            ]
            qa_section = "\n\nCLARIFYING Q&A:\n" + "\n\n".join(qa_lines)

    # Build template section
    template_section = ""
    if app_spec_template:
        template_section += (
            f"\n\n=== TEMPLATE: app_spec.txt ===\n{app_spec_template}"
        )
    if initializer_template:
        template_section += (
            f"\n\n=== TEMPLATE: initializer_prompt.md ===\n{initializer_template}"
        )
    if coding_template:
        template_section += (
            f"\n\n=== TEMPLATE: coding_prompt.md ===\n{coding_template}"
        )

    query = (
        "Generate the three prompt files for this project.\n\n"
        f"REQUIREMENTS DOCUMENT:\n{content}"
        f"{qa_section}\n\n"
        f"FORMAT TEMPLATES (follow the exact structure):{template_section}\n\n"
        "For app_spec.txt: Create a detailed XML specification following the "
        "<project_specification> format shown in any existing example.\n"
        "For initializer_prompt.md: Follow the INITIALIZER AGENT template format exactly.\n"
        "For coding_prompt.md: Follow the CODING AGENT template format exactly.\n\n"
        "Customize all content for the specific project described above.\n"
        "Output requirements:\n"
        "- Return exactly one JSON object.\n"
        "- Do not include markdown fences.\n"
        "- Do not include explanations before or after JSON.\n"
        "- The response must start with { and end with }.\n"
        "- Include exactly these keys: app_spec, initializer_prompt, coding_prompt.\n"
        "- Ensure all newlines inside values are valid JSON escaped newlines."
    )

    cfg = get_config()
    result = run_prompt_task(
        provider_id=provider_id,
        model=model,
        system_prompt=GENERATION_SYSTEM_PROMPT,
        prompt=query,
        cwd=Path.cwd(),
        cfg=cfg,
        allowed_tools="Edit,Bash,Task",
        stream_callback=stream_callback,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr[:500] or "(no stderr)")

    try:
        return extract_json_from_text(
            result.stdout,
            required_keys=GENERATION_REQUIRED_KEYS,
            exact_keys=True,
        )
    except ValueError as first_error:
        print("Generation output was malformed. Retrying once with strict repair instructions...\n")

        repair_query = (
            "Your previous output could not be parsed as valid JSON.\n\n"
            f"Parse error:\n{first_error}\n\n"
            "Re-output the content as a single valid JSON object only.\n"
            "Rules:\n"
            "- No markdown fences.\n"
            "- No explanation.\n"
            "- Start with { and end with }.\n"
            "- Include exactly these keys: app_spec, initializer_prompt, coding_prompt.\n\n"
            "Previous output to repair:\n"
            f"{result.stdout[:12000]}"
        )

        retry_result = run_prompt_task(
            provider_id=provider_id,
            model=model,
            system_prompt=GENERATION_SYSTEM_PROMPT,
            prompt=repair_query,
            cwd=Path.cwd(),
            cfg=cfg,
            allowed_tools="Edit,Bash,Task",
            stream_callback=stream_callback,
        )

        if retry_result.returncode != 0:
            raise RuntimeError(
                f"Generation retry failed: {retry_result.stderr[:500] or '(no stderr)'}"
            ) from first_error

        try:
            return extract_json_from_text(
                retry_result.stdout,
                required_keys=GENERATION_REQUIRED_KEYS,
                exact_keys=True,
            )
        except ValueError as second_error:
            raise RuntimeError(
                "Generation failed after one retry.\n"
                f"First parse error: {first_error}\n"
                f"Second parse error: {second_error}\n"
                f"Second output preview:\n{retry_result.stdout[:500]}"
            ) from second_error


def write_prompt_files(
    generated: dict,
    prompts_dir: Path,
    overwrite: bool = False,
    status_callback: StatusCallback | None = None,
) -> None:
    """
    Phase 5: Write the generated files to disk.

    Skips any file that already exists unless overwrite=True.

    Args:
        generated: Dict with keys app_spec, initializer_prompt, coding_prompt.
        prompts_dir: Directory to write files into (created if missing).
        overwrite: If True, overwrite existing files; otherwise skip with warning.
    """
    print("\n" + "=" * 60)
    print("PHASE 5 — Writing Files")
    print("=" * 60)
    if status_callback:
        status_callback("write", "Writing generated prompt files")

    prompts_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "app_spec.txt": generated.get("app_spec", ""),
        "initializer_prompt.md": apply_autonomy_override(
            generated.get("initializer_prompt", ""),
            enabled=get_config().prompt_autonomy_override,
        ),
        "coding_prompt.md": apply_autonomy_override(
            generated.get("coding_prompt", ""),
            enabled=get_config().prompt_autonomy_override,
        ),
    }

    for filename, file_content in files.items():
        if not file_content:
            print(f"  WARNING: No content generated for {filename}, skipping.")
            continue

        path = prompts_dir / filename
        if path.exists() and not overwrite:
            print(
                f"  WARNING: {path} already exists. "
                "Use --prompt-overwrite to overwrite."
            )
            if status_callback:
                status_callback("write", f"Skipped existing file: {path}")
            continue

        path.write_text(file_content, encoding="utf-8")
        print(f"  Written: {path}")
        if status_callback:
            status_callback("write", f"Written: {path}")

    print()


async def run_prompter(
    prompt_files: list[str] | None = None,
    analysis_model: str | None = None,
    generation_model: str | None = None,
    overwrite: bool = False,
    provider_id: str | None = None,
    source_content: str | None = None,
    qa_answers: list[str] | None = None,
    status_callback: StatusCallback | None = None,
    stream_callback: StreamCallback | None = None,
) -> bool:
    """
    Orchestrate all five phases of the prompt wizard.

    Args:
        prompt_files: File paths to use as source material. If None, prompts
                      user to paste text interactively.
        analysis_model: Model for Phase 2 analysis (default: haiku).
        generation_model: Model for Phase 4 generation (default: sonnet).
        overwrite: If True, overwrite existing prompts/ files.
    """
    cfg = get_config()
    provider = provider_id or cfg.agent_cli_id
    if analysis_model is None:
        analysis_model = provider_default_model(provider, cfg) or DEFAULT_ANALYSIS_MODEL
    if generation_model is None:
        generation_model = provider_default_model(provider, cfg) or DEFAULT_GENERATION_MODEL

    prompts_dir = Path("prompts")

    print("\n" + "=" * 60)
    print("PROMPT WIZARD")
    print("=" * 60)
    print("This wizard generates prompts/ files from your requirements.")
    print()

    # Phase 1: Collect source documents
    try:
        content = source_content if source_content is not None else collect_source_documents(prompt_files)
        if not content.strip():
            raise ValueError("No requirements provided. Please provide a requirements document.")
    except (ValueError, FileNotFoundError) as e:
        print(f"\nError: {e}")
        return False

    # Phase 2: Analysis session
    try:
        analysis_result = await run_analysis_session(
            content,
            analysis_model,
            provider,
            status_callback=status_callback,
            stream_callback=stream_callback,
        )
    except Exception as e:
        print(f"\nError during analysis: {e}")
        return False

    questions = analysis_result.get("questions", [])

    # Phase 3: Q&A with user
    qa_pairs = conduct_qa(questions, answers=qa_answers) if questions else []

    # Phase 4: Generation session
    try:
        generated = await run_generation_session(
            content,
            qa_pairs,
            generation_model,
            provider,
            status_callback=status_callback,
            stream_callback=stream_callback,
        )
    except Exception as e:
        print(f"\nError during generation: {e}")
        return False

    # Phase 5: Write files
    write_prompt_files(
        generated,
        prompts_dir,
        overwrite=overwrite,
        status_callback=status_callback,
    )
    return True


if __name__ == "__main__":
    asyncio.run(run_prompter())
