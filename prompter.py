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

from claude_code_sdk import ClaudeCodeOptions, ClaudeSDKClient

from configure import extract_json_from_text


DEFAULT_ANALYSIS_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_GENERATION_MODEL = "claude-sonnet-4-6"

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


async def run_analysis_session(content: str, model: str) -> dict:
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

    query = (
        "Please analyze the following requirements document and generate clarifying questions.\n\n"
        f"REQUIREMENTS DOCUMENT:\n{content}\n\n"
        "Output ONLY a valid JSON object as described in your instructions."
    )

    client = ClaudeSDKClient(
        options=ClaudeCodeOptions(
            model=model,
            system_prompt=ANALYSIS_SYSTEM_PROMPT,
            allowed_tools=[],
            max_turns=5,
            cwd=str(Path.cwd()),
        )
    )

    collected_text = ""

    async with client:
        await client.query(query)

        async for msg in client.receive_response():
            msg_type = type(msg).__name__
            if msg_type == "AssistantMessage" and hasattr(msg, "content"):
                for block in msg.content:
                    block_type = type(block).__name__
                    if block_type == "TextBlock" and hasattr(block, "text"):
                        collected_text += block.text

    result = extract_json_from_text(collected_text)

    print(f"Analysis: {result.get('analysis', '?')}")
    print(f"Questions identified: {len(result.get('questions', []))}\n")

    return result


def conduct_qa(questions: list[dict]) -> list[dict]:
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
    for i, q in enumerate(questions, 1):
        question = q.get("question", "")
        why = q.get("why", "")

        print(f"Q{i}: {question}")
        if why:
            print(f"     (Why: {why})")

        try:
            answer = input("A: ").strip()
        except EOFError:
            answer = ""

        qa_pairs.append({"question": question, "answer": answer})
        print()

    return qa_pairs


def _load_template(filename: str) -> str:
    """Load a template file from the prompts/ directory alongside this script."""
    template_path = Path(__file__).parent / "prompts" / filename
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    return ""


async def run_generation_session(
    content: str, qa_pairs: list[dict], model: str
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

    # Load template examples from the existing prompts/ directory
    initializer_template = _load_template("initializer_prompt.md")
    coding_template = _load_template("coding_prompt.md")

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
        "Output ONLY a valid JSON object with keys: app_spec, initializer_prompt, coding_prompt."
    )

    client = ClaudeSDKClient(
        options=ClaudeCodeOptions(
            model=model,
            system_prompt=GENERATION_SYSTEM_PROMPT,
            allowed_tools=[],
            max_turns=10,
            cwd=str(Path.cwd()),
        )
    )

    collected_text = ""

    async with client:
        await client.query(query)

        async for msg in client.receive_response():
            msg_type = type(msg).__name__
            if msg_type == "AssistantMessage" and hasattr(msg, "content"):
                for block in msg.content:
                    block_type = type(block).__name__
                    if block_type == "TextBlock" and hasattr(block, "text"):
                        collected_text += block.text
                        # Show progress without printing raw JSON
                        if not block.text.strip().startswith("{"):
                            print(block.text, end="", flush=True)

    print("\n")

    return extract_json_from_text(collected_text)


def write_prompt_files(
    generated: dict, prompts_dir: Path, overwrite: bool = False
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

    prompts_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "app_spec.txt": generated.get("app_spec", ""),
        "initializer_prompt.md": generated.get("initializer_prompt", ""),
        "coding_prompt.md": generated.get("coding_prompt", ""),
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
            continue

        path.write_text(file_content, encoding="utf-8")
        print(f"  Written: {path}")

    print()


async def run_prompter(
    prompt_files: list[str] | None = None,
    analysis_model: str | None = None,
    generation_model: str | None = None,
    overwrite: bool = False,
) -> None:
    """
    Orchestrate all five phases of the prompt wizard.

    Args:
        prompt_files: File paths to use as source material. If None, prompts
                      user to paste text interactively.
        analysis_model: Model for Phase 2 analysis (default: haiku).
        generation_model: Model for Phase 4 generation (default: sonnet).
        overwrite: If True, overwrite existing prompts/ files.
    """
    if analysis_model is None:
        analysis_model = DEFAULT_ANALYSIS_MODEL
    if generation_model is None:
        generation_model = DEFAULT_GENERATION_MODEL

    prompts_dir = Path("prompts")

    print("\n" + "=" * 60)
    print("PROMPT WIZARD")
    print("=" * 60)
    print("This wizard generates prompts/ files from your requirements.")
    print()

    # Phase 1: Collect source documents
    try:
        content = collect_source_documents(prompt_files)
    except (ValueError, FileNotFoundError) as e:
        print(f"\nError: {e}")
        return

    # Phase 2: Analysis session
    try:
        analysis_result = await run_analysis_session(content, analysis_model)
    except Exception as e:
        print(f"\nError during analysis: {e}")
        return

    questions = analysis_result.get("questions", [])

    # Phase 3: Q&A with user
    qa_pairs = conduct_qa(questions) if questions else []

    # Phase 4: Generation session
    try:
        generated = await run_generation_session(content, qa_pairs, generation_model)
    except Exception as e:
        print(f"\nError during generation: {e}")
        return

    # Phase 5: Write files
    write_prompt_files(generated, prompts_dir, overwrite=overwrite)


if __name__ == "__main__":
    asyncio.run(run_prompter())
