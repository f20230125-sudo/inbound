"""Independent source layouts. Gold records are authored in cases.json, never inferred here."""


def office(s):
    if s["layout"] == "held-out":
        return "\n".join(
            [
                s["intro"],
                "Intake details",
                s["mode"],
                s["link"],
                "Allowance details:",
                s["stipend"],
                s["jd"],
                s["conditions"],
                s["website"],
                s["deadline"],
                s["signature"],
                s["note"],
            ]
        )
    return "\n".join(
        [
            s["intro"],
            s["link"],
            s["website"],
            "*Stipend*",
            s["stipend"],
            s["mode"],
            s["jd"],
            s["conditions"],
            s["deadline"],
            s["note"],
            s["signature"],
        ]
    )


def reminder(s):
    if s["layout"] == "held-out":
        return "\n".join(
            [
                "Please note the current closing arrangements below.",
                s["recap"],
                s["jd"],
                s["deadline"],
                s["link"],
                "",
                "--- Original message ---",
                s["quoted"],
            ]
        )
    return "\n".join(
        [
            "Reminder for the current intake.",
            s["deadline"],
            s["recap"],
            s["link"],
            s["jd"],
            "",
            "--- Original message ---",
            s["quoted"],
        ]
    )


def direct(s):
    if s["layout"] == "held-out":
        return "\n".join(
            [
                "External recruitment route",
                s["intro"],
                s["website"],
                s["jd"],
                s["mode"],
                s["link"],
                "Applications go to the employer.",
                s["signature"],
            ]
        )
    return "\n".join(
        [
            s["intro"],
            s["website"],
            s["link"],
            s["mode"],
            s["jd"],
            "Please apply directly through the careers page.",
            s["signature"],
        ]
    )


def multi_role(s):
    if s["layout"] == "held-out":
        return "\n".join(
            [
                s["intro"],
                s["jd"],
                "Terms for this intake",
                s["mode"],
                s["stipend"],
                s["deadline"],
                s["link"],
                s["signature"],
            ]
        )
    return "\n".join(
        [s["intro"], s["link"], s["stipend"], s["mode"], s["jd"], s["deadline"], s["signature"]]
    )


def pdf(s):
    if s["layout"] == "held-out":
        return "\n".join(
            [
                s["intro"],
                "JD location:\n· Attached",
                s["mode"],
                s["stipend"],
                s["link"],
                s["deadline"],
                s["signature"],
            ]
        )
    return "\n".join(
        [
            s["intro"],
            s["link"],
            "*Stipend*",
            s["stipend"],
            s["mode"],
            "*Job Title & JD*",
            "· Attached",
            s["deadline"],
            s["signature"],
        ]
    )


def docx(s):
    if s["layout"] == "held-out":
        return "\n".join(
            [
                s["intro"],
                s["conditions"],
                "Position details: DOCX\n· Attached",
                s["mode"],
                s["deadline"],
                s["stipend"],
                s["link"],
                s["signature"],
            ]
        )
    return "\n".join(
        [
            s["intro"],
            "The role description is supplied in a Word document.",
            s["link"],
            s["stipend"],
            s["mode"],
            "*JD*\n· Attached",
            s["conditions"],
            s["deadline"],
            s["signature"],
        ]
    )


def render(case):
    source = case["message"]
    if "body" in source:
        return source["body"]
    renderers = {"A": office, "B": reminder, "C": direct, "D": multi_role, "E": pdf, "F": docx}
    return renderers[case["family"]](source["sections"])
