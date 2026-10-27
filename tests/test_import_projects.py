import pytest

from inbound.evidence.import_projects import merge_projects, parse_projects


def test_constrained_nested_objects_and_gh():
    source = """const GH = "https://code.invalid/me";
    export const projects: Project[] = [{id:"one", name:"One", stack:["Python"],
      code:`${GH}/one`, live:{url:"https://one.invalid", note:"braces { }"},
      shots:[{alt:"quote \\\" and // literal"}], decisions:["Fix ties."]}];"""
    p = parse_projects(source)[0]
    assert p["code"] == "https://code.invalid/me/one"
    assert p["live"]["url"] == "https://one.invalid"
    assert p["decisions"] == ["Fix ties."]


@pytest.mark.parametrize("value", ["evil()", "process.env.SECRET", "`${evil()}`", "...other"])
def test_executable_syntax_rejected(value):
    with pytest.raises(ValueError):
        parse_projects('const GH="x"; export const projects = [{id:"one", x:' + value + "}];")


def test_missing_portfolio_project_keeps_cv_evidence():
    data = {"projects": [{"id": "missing", "bullets": [{"id": "b"}], "title": "Missing"}]}
    assert merge_projects(data, []) == data
