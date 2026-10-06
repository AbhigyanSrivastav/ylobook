class ReceivingPolicy:
    """Small local policy boundary for inbound network activity."""

    def allow_contact_request(self, request: dict) -> bool:
        return True

    def allow_message(self, message: dict) -> bool:
        return True
