class PolicyError(ValueError):
    pass


class PayloadPolicy:
    """Check trusted import provenance before any future cache/provider boundary."""

    def check(self, sources):
        values = set(sources)
        if len(values) != 1 or not values <= {"synthetic", "public"}:
            raise PolicyError("Payload provenance denied")

    def authorize(self, payload, trusted_sources):
        self.check(trusted_sources)
        return payload
