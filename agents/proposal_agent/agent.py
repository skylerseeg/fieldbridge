"""
Proposal Writing Agent
Multi-step agent that assembles a complete bid proposal using project experience,
company capabilities, bid scope, and project photos. Uses prompt caching.
"""
import anthropic

client = anthropic.Anthropic()

MODEL = "claude-sonnet-4-20250514"

_SYSTEM_PROMPT = """
You are a senior proposal writer for VanCon Inc., a heavy civil contractor
specializing in water/wastewater utilities, earthwork, and paving for public agencies.

Writing rules:
- Lead with VanCon's specific, verifiable project experience. No generic claims.
- Match tone to the RFP: technical for engineers, narrative for owners.
- Quantify everything: pipe diameters, depths, HP ratings, contract values, schedule.
- Safety record and team qualifications anchor credibility.
- Avoid boilerplate. Every section must be tailored to this specific project.
"""

_SECTION_PROMPTS = {
    "executive_summary": (
        "Write a 2-3 paragraph executive summary for this proposal. "
        "Lead with why VanCon is uniquely qualified, reference 2-3 specific past projects, "
        "and close with a commitment statement. Context: {context}"
    ),
    "experience": (
        "Write an experience section listing VanCon's most relevant past projects. "
        "For each project include: name, owner, engineer, contract value, year, "
        "key scope items matching this RFP, and notable achievements. Context: {context}"
    ),
    "approach": (
        "Write a technical approach section describing how VanCon will execute this project. "
        "Cover: construction sequence, key methods, quality control, schedule strategy, "
        "and risk mitigation. Context: {context}"
    ),
    "team": (
        "Write a key personnel section. List the proposed PM, superintendent, "
        "and foremen with relevant experience. Keep it factual and project-specific. "
        "Context: {context}"
    ),
    "safety": (
        "Write a safety section covering VanCon's safety program, EMR rating, "
        "incident record, and site-specific safety plan approach. Context: {context}"
    ),
}


def write_section(section_type: str, context: dict) -> str:
    """
    section_type: 'executive_summary' | 'experience' | 'approach' | 'team' | 'safety'
    context: dict with project data, scope, client name, relevant past projects, etc.
    """
    if section_type not in _SECTION_PROMPTS:
        raise ValueError(f"Unknown section type: {section_type}. "
                         f"Must be one of: {list(_SECTION_PROMPTS.keys())}")

    prompt_template = _SECTION_PROMPTS[section_type]
    import json
    context_str = json.dumps(context, indent=2, default=str)
    prompt = prompt_template.format(context=context_str)

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def assemble_proposal(project_context: dict,
                      past_projects: list[dict],
                      sections: list[str] | None = None) -> dict:
    """
    Assemble a full proposal by writing all requested sections.

    project_context: RFP details — client, scope, deadline, contract value estimate
    past_projects: ranked list from project_search_agent
    sections: list of section keys to generate (default: all)
    """
    if sections is None:
        sections = list(_SECTION_PROMPTS.keys())

    context = {**project_context, "past_projects": past_projects}
    proposal: dict[str, str] = {}

    for section in sections:
        proposal[section] = write_section(section, context)

    return proposal
