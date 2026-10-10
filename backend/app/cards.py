"""Published CardKit templates verified against their source and version history."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CardTemplate:
    id: str
    version: str


TEMPLATES = {
    "plus": CardTemplate("AAqzjRLLF2LbI", "1.0.4"),
    "minus": CardTemplate("AAqzj4Y1vmkf7", "1.0.3"),
}


def department_text(person):
    paths = sorted({" / ".join(path["names"]) for path in person["paths"] if path["names"]})
    return "；".join(paths) or "直属企业"


def template_card(context, operation):
    template = TEMPLATES[operation]
    # All five variables are CardKit text variables. The plus template adds its
    # own '+'; the minus template has no sign prefix, so score carries the '-'.
    variables = {
        "department": context["department"],
        "user_name": context["person_name"],
        "reason": context["reason"],
        "score": str(context["delta"]),
        "total_score": str(context["total"]),
    }
    return {"type": "template", "data": {
        "template_id": template.id,
        "template_version_name": template.version,
        "template_variable": variables,
    }}
