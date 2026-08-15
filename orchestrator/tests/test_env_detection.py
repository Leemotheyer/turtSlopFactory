from app.services.env_detection import detect_env_keys_from_text


def test_detect_komga_and_login_keys():
    text = "Proxy a Komga server with login page and user credentials"
    keys = {k for k, _ in detect_env_keys_from_text(text)}
    assert "KOMGA_BASE_URL" in keys
    assert "APP_USERNAME" in keys or "KOMGA_USERNAME" in keys


def test_detect_api_key_generic():
    keys = detect_env_keys_from_text("Requires an API key for the weather service")
    assert any(k == "API_KEY" for k, _ in keys)
