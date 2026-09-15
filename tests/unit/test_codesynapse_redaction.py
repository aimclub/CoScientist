from CoScientist.integrations.codesynapse.redaction import redact


def test_redact_masks_secrets_and_bearer_capabilities_recursively():
    payload = {
        "api_key": "provider-secret",
        "nested": {"Authorization": "Bearer token-value"},
        "items": [{"presigned_url": "https://storage.example/object?signature=secret"}],
        "safe": "visible",
    }

    assert redact(payload) == {
        "api_key": "***redacted***",
        "nested": {"Authorization": "***redacted***"},
        "items": [{"presigned_url": "***redacted***"}],
        "safe": "visible",
    }


def test_redact_masks_secret_values_that_are_not_under_sensitive_keys():
    assert redact({"log": "Authorization: Bearer abc.def-123", "aws": "AKIA1234567890ABCDEF"}) == {
        "log": "Authorization: ***redacted***",
        "aws": "***redacted***",
    }
