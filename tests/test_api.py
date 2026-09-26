import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.errors import LLMRateLimited
from app.llm import providers
from app.voice import assemblyai


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'api.db'}")
    import importlib
    import app.main as main
    importlib.reload(main)
    # no provider configured -> offline path
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "assemblyai_api_key", "")
    main._hits.clear()
    return TestClient(main.app)


def test_health(client):
    d = client.get("/api/health").json()
    assert d["ok"] and d["llm_configured"] is False and d["assemblyai_configured"] is False
    assert [p["name"] for p in d["llm_providers"]] == ["gemini", "groq", "openrouter"]


def test_index_and_static(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_session_chat_history_roundtrip(client):
    sid = client.post("/api/sessions").json()["session_id"]
    r = client.post("/api/chat", json={"session_id": sid, "message": "solve 2x + 7 = 15", "source": "voice", "mode": "hackathon"})
    assert r.status_code == 200
    d = r.json()
    assert d["response"]["segments"][1]["type"] == "math" and d["output"]["speak"] is True
    hist = client.get(f"/api/sessions/{sid}/history").json()["messages"]
    assert len(hist) == 2 and hist[1]["metadata"]["response"]["segments"]
    assert client.delete(f"/api/sessions/{sid}").json()["ok"]


def test_chat_with_unknown_session_id_creates_it(client):
    r = client.post("/api/chat", json={"session_id": "brand-new", "message": "hello"})
    assert r.status_code == 200 and r.json()["error"] is None


def test_chat_validation(client):
    assert client.post("/api/chat", json={"session_id": "x", "message": ""}).status_code == 422


def test_assemblyai_token_needs_key(client):
    r = client.get("/api/assemblyai/token?language=en")
    assert r.status_code == 503 and r.json()["error"]["kind"] == "assemblyai_not_configured"
    assert client.get("/api/assemblyai/token?language=xx").status_code == 422


def test_run_disabled_by_default(client):
    assert client.post("/api/run", json={"code": "print(1)"}).status_code == 403


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_min", 3)
    codes = [client.post("/api/chat", json={"session_id": "r", "message": "hello"}).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429


# ---------------------------------------------------------- AssemblyAI token wire format
class _Resp:
    def __init__(self, status, body): self.status_code, self._b = status, body
    def json(self): return self._b


def _fake_client(captured, status=200, body=None):
    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None, headers=None):
            captured.update(url=url, params=params, headers=headers)
            return _Resp(status, body if body is not None else {"token": "tmp-token"})
    return C


def test_assemblyai_token_uses_raw_key_header_no_bearer(monkeypatch):
    import asyncio
    cap = {}
    monkeypatch.setattr(settings, "assemblyai_api_key", "KEY123")
    monkeypatch.setattr(assemblyai.httpx, "AsyncClient", _fake_client(cap))
    out = asyncio.run(assemblyai.create_token("en"))
    assert cap["headers"] == {"Authorization": "KEY123"}          # no "Bearer"
    assert cap["url"] == "https://streaming.assemblyai.com/v3/token"
    assert out["token"] == "tmp-token" and out["params"]["speech_model"] == "universal-3-5-pro"
    assert "KEY123" not in str(out)                                # permanent key never returned


def test_assemblyai_language_models(monkeypatch):
    assert assemblyai.stream_params("gu")["speech_model"] == "whisper-rt"
    assert assemblyai.stream_params("gu")["language_detection"] == "true"
    assert assemblyai.stream_params("hi")["speech_model"] == "universal-3-5-pro"


def test_assemblyai_auth_error_is_typed(monkeypatch):
    import asyncio
    from app.errors import STTError
    monkeypatch.setattr(settings, "assemblyai_api_key", "BAD")
    monkeypatch.setattr(assemblyai.httpx, "AsyncClient", _fake_client({}, status=401, body={}))
    with pytest.raises(STTError) as e:
        asyncio.run(assemblyai.create_token("en"))
    assert e.value.kind == "assemblyai_auth_failed" and e.value.layer == "stt"


# ------------------------------------------------------------- provider wire formats
def _capture_post(captured, status=200, body=None):
    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None, **k):
            captured.update(url=url, headers=headers, json=json)
            return httpx.Response(status, json=body or {}, request=httpx.Request("POST", url))
    return C


def test_gemini_request_shape(monkeypatch):
    import asyncio
    cap = {}
    monkeypatch.setattr(settings, "gemini_api_key", "G")
    monkeypatch.setattr(providers.httpx, "AsyncClient", _capture_post(cap, body={"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}))
    out = asyncio.run(providers.GeminiProvider().complete("sys", [{"role": "user", "content": "yo"}], json_mode=True))
    assert out == "hi"
    assert cap["headers"]["x-goog-api-key"] == "G" and "key=" not in cap["url"]      # key not in URL
    assert cap["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert cap["json"]["systemInstruction"]["parts"][0]["text"] == "sys"


def test_groq_request_shape_and_429(monkeypatch):
    import asyncio
    cap = {}
    monkeypatch.setattr(settings, "groq_api_key", "K")
    prov = providers.build_provider("groq")
    monkeypatch.setattr(providers.httpx, "AsyncClient", _capture_post(cap, body={"choices": [{"message": {"content": "ok"}}]}))
    assert asyncio.run(prov.complete("s", [{"role": "user", "content": "u"}])) == "ok"
    assert cap["url"].endswith("/openai/v1/chat/completions") and cap["headers"]["Authorization"] == "Bearer K"
    assert cap["json"]["messages"][0] == {"role": "system", "content": "s"}
    monkeypatch.setattr(providers.httpx, "AsyncClient", _capture_post({}, status=429, body={"error": "slow"}))
    with pytest.raises(LLMRateLimited):
        asyncio.run(prov.complete("s", [{"role": "user", "content": "u"}]))
