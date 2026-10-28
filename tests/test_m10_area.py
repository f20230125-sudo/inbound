"""Body `Company,City,Area` after a subject `Company,City` is one identity, not a conflict."""

from datetime import UTC, datetime

from inbound.extract.call import extract_call
from inbound.models import Message

Z = chr(0x200B)
SENT = datetime(2026, 10, 27, 6, tzinfo=UTC)


def extract(subject, opening):
    message = Message(
        provider_id="area", thread_id="area", sent_at=SENT, received_at=SENT,
        sender="ps@dubai.bits-pilani.ac.in", subject=subject, source="synthetic",
        body_text=f"{opening}has expressed their interest to hire Students for PS II.\n"
                  "*CV Submission Deadline**: **: 08**:00AM , 29 October 2026*\n",
    )
    return extract_call(message, [], category="ps_call")["fields"]


PREFIX = "Call for CV - PS II – Second Semester 2026-2027 – "


def test_area_after_city_in_body_keeps_company_and_city_found():
    fields = extract(PREFIX + "Harbor Finch,Port Selene", "*Harbor Finch,Port Selene,Marina Quarter, *")
    assert (fields["company"]["status"], fields["company"]["normalized"]) == ("found", "Harbor Finch")
    assert (fields["city"]["status"], fields["city"]["normalized"]) == ("found", "Port Selene")


def test_zero_width_subject_and_comma_company_with_area():
    fields = extract(
        PREFIX + f"Brightwater Solutions/Al Noor, Harbor District,{Z}Port Selene",
        "*Brightwater Solutions/Al Noor, Harbor District,Port Selene,Marina, *",
    )
    assert fields["company"]["normalized"] == "Brightwater Solutions/Al Noor, Harbor District"
    assert fields["city"]["normalized"] == "Port Selene"


def test_a_genuinely_different_body_company_still_conflicts():
    fields = extract(PREFIX + "Alpha Labs,Port Selene", "*Beta Labs,Port Selene,Marina, *")
    assert fields["company"]["status"] == "conflicting"


def test_area_rule_does_not_hide_a_company_that_really_differs():
    # Body company "Alpha, Labs" is not the subject's "Alpha": keep the conflict visible.
    fields = extract(PREFIX + "Alpha,Port Selene", "*Alpha, Labs,Port Selene, *")
    assert fields["company"]["status"] == "conflicting"
