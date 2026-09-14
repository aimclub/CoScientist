from CoScientist.integrations.codesynapse.settings import CodesynapseIntegrationSettings


def test_codesynapse_settings_have_safe_disabled_defaults():
    settings = CodesynapseIntegrationSettings()

    assert not settings.enabled
    assert settings.missing_readiness_requirements() == []


def test_codesynapse_settings_do_not_require_jwks_when_enabled():
    settings = CodesynapseIntegrationSettings(
        enabled=True,
        mongo_uri="mongodb://localhost:27017",
        a2a_public_url="http://localhost:8010",
    )

    assert settings.missing_readiness_requirements() == []
