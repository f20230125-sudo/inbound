import pytest

from inbound.policy import PayloadPolicy, PolicyError


@pytest.mark.parametrize(
    "sources",
    [
        [],
        ["private"],
        ["unknown"],
        ["synthetic", "private"],
        ["public", "unknown"],
        ["synthetic", "public"],
    ],
)
def test_fail_closed(sources):
    with pytest.raises(PolicyError):
        PayloadPolicy().check(sources)


@pytest.mark.parametrize("source", ["synthetic", "public"])
def test_allowed(source):
    PayloadPolicy().check([source])


def test_payload_cannot_override_provenance():
    with pytest.raises(PolicyError):
        PayloadPolicy().authorize({"source": "synthetic", "body": "private-like"}, ["private"])
