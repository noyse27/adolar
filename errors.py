"""Shared exception types for Adolar.

ValidationError carries a curated, user-facing German message that is safe to
return in an API response. Raise it for invalid client input; keep plain
ValueError for internal programming errors, whose text must never reach a
client (CodeQL py/stack-trace-exposure).
"""


class ValidationError(ValueError):
    def __init__(self, user_message: str):
        super().__init__(user_message)
        # Read this attribute (not str(exc)) when building an API response:
        # it marks the message as deliberately written for end users.
        self.user_message = user_message
