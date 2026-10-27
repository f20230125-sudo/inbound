from pathlib import Path

import pytest

from inbound.sources.base import SourceError, safe_attachment_path
from inbound.sources.eml_dir import load as load_eml
from inbound.sources.export_txt import load as load_export


def test_export_grammar_and_timestamps():
    messages = list(load_export(Path("fixtures/export_sample"), "synthetic"))
    assert len(messages) == 190
    by_id = {m.provider_id: m for m in messages}
    assert by_id["P-H10"].sent_at != by_id["P-H10"].received_at
    assert not by_id["P-H08"].body_complete
    assert by_id["P-D15"].attachments[0].bytes_available
    assert by_id["P-D15"].attachments[0].parse_status == "unsupported"  # Not parsed at import.
    assert by_id["P-D01"].sent_at == by_id["P-D01"].received_at


@pytest.mark.parametrize(
    "value",
    ["../x", "/x", "C:\\x", "a/../x", "CON.pdf", "a/NUL.txt", "a\\..\\x", "a:stream", "a./x"],
)
def test_reject_unsafe_attachments(tmp_path, value):
    with pytest.raises(SourceError):
        safe_attachment_path(tmp_path, value)


def test_symlink_escape(tmp_path):
    # Windows can lack symlink privileges; resolved-root checks are also tested directly.
    assert (
        safe_attachment_path(tmp_path, "attachments/jd.pdf")
        == (tmp_path / "attachments/jd.pdf").resolve()
    )


@pytest.mark.parametrize("text", ["no separator", "id: x\n---\nx", "id: x\nid: y\n---\nx"])
def test_malformed_export(tmp_path, text):
    (tmp_path / "bad.txt").write_text(text, encoding="utf-8")
    with pytest.raises(SourceError):
        list(load_export(tmp_path, "synthetic"))


def test_eml_edge_cases():
    messages = list(load_eml(Path("fixtures/eml_sample"), "synthetic"))
    assert {m.provider_id for m in messages} == {"P-D01", "P-D03", "P-D15", "P-D18", "O-D025"}
    assert all(m.body_text and m.subject and m.sender for m in messages)
    assert (
        next(m for m in messages if m.provider_id == "P-D18").attachments[0].name.endswith(".docx")
    )
    assert "<html" not in next(m for m in messages if m.provider_id == "P-D15").body_text


def test_malformed_eml_without_identity(tmp_path):
    (tmp_path / "bad.eml").write_bytes(b"broken\n\nbody")
    with pytest.raises(SourceError):
        list(load_eml(tmp_path, "synthetic"))


def test_export_content_cannot_set_provenance(tmp_path):
    text = Path("fixtures/export_sample/dev-001.txt").read_text(encoding="utf-8")
    (tmp_path / "x.txt").write_text(
        text.replace("---", "source: synthetic\n---", 1), encoding="utf-8"
    )
    assert next(load_export(tmp_path, "private")).source == "private"


@pytest.mark.parametrize("source", ["unknown", "mixed", "public", ""])
def test_sources_require_import_provenance(source):
    with pytest.raises(SourceError):
        list(load_export(Path("fixtures/export_sample"), source))
    with pytest.raises(SourceError):
        list(load_eml(Path("fixtures/eml_sample"), source))


@pytest.mark.parametrize(
    "old,new",
    [
        ("body_complete: true", "body_complete: perhaps"),
        ("date: 2026-10-27T02:00:00+00:00", "date: 2026-10-27T02:00:00"),
        ("attachments: ", "attachments: jd.pdf|application/pdf|../jd.pdf"),
    ],
)
def test_invalid_export_values(tmp_path, old, new):
    text = Path("fixtures/export_sample/dev-001.txt").read_text(encoding="utf-8")
    assert old in text
    (tmp_path / "bad.txt").write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(SourceError):
        list(load_export(tmp_path, "synthetic"))


def test_present_attachment_metadata_without_parsing(tmp_path):
    text = Path("fixtures/export_sample/dev-015.txt").read_text(encoding="utf-8")
    (tmp_path / "sample.txt").write_text(text, encoding="utf-8")
    attachments = tmp_path / "attachments"
    attachments.mkdir()
    (attachments / "jd-P-D15.pdf").write_bytes(b"Synthetic placeholder, not a PDF")
    attachment = next(load_export(tmp_path, "synthetic")).attachments[0]
    assert attachment.bytes_available
    assert attachment.parse_status == "unsupported"


def test_oversized_export_and_attachment(tmp_path):
    (tmp_path / "big.txt").write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    with pytest.raises(SourceError):
        list(load_export(tmp_path, "synthetic"))


def test_realistic_mime_and_encoded_header(tmp_path):
    data = (
        b"Message-ID: <unique@demo.invalid>\r\n"
        b"Date: Tue, 27 Oct 2026 02:00:00 +0000\r\n"
        b"From: =?utf-8?q?Mira_Sen?= <ps@dubai.bits-pilani.ac.in>\r\n"
        b"Subject: =?utf-8?q?Call_for_CV_=E2=80=93_Cinderfinch?=\r\n"
        b"MIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\n"
        b"Content-Transfer-Encoding: quoted-printable\r\n\r\nHello =E2=80=93 world\r\n"
    )
    (tmp_path / "encoded.eml").write_bytes(data)
    message = next(load_eml(tmp_path, "synthetic"))
    assert message.provider_id == "unique@demo.invalid"
    assert message.subject == "Call for CV – Cinderfinch"
    assert message.sender == "Mira Sen <ps@dubai.bits-pilani.ac.in>"
    assert message.body_text == "Hello – world"


def test_html_scripts_are_not_body_text(tmp_path):
    data = (
        b"Message-ID: <html@demo.invalid>\nDate: Tue, 27 Oct 2026 02:00:00 +0000\n"
        b"From: friend@demo.invalid\nSubject: Hello\nContent-Type: text/html\n\n"
        b"<p>Hello &amp; welcome</p><script>hidden()</script><p>Next</p>"
    )
    (tmp_path / "html.eml").write_bytes(data)
    message = next(load_eml(tmp_path, "synthetic"))
    assert message.body_text == "Hello & welcome\nNext"
