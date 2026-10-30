from app.core.config import Settings


def test_printing_settings_never_shows_secrets():
    settings = Settings(
        _env_file=None,
        llm_api_key="llm-secret",
        database_url="postgresql+asyncpg://user:db-secret@host:5432/db",
        surya_inference_api_key="surya-secret",
        embedding_api_key="embedding-secret",
    )
    for shown in (repr(settings), str(settings), str(settings.model_dump())):
        for secret in ("llm-secret", "db-secret", "surya-secret", "embedding-secret"):
            assert secret not in shown
    assert settings.database_url.get_secret_value().endswith("db-secret@host:5432/db")
