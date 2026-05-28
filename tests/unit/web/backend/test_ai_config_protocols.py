from web.backend.schemas import AIConfigRequest


def test_ai_config_request_accepts_protocol_field():
    req = AIConfigRequest(
        provider="mimo",
        protocol="anthropic",
        api_key="secret",
        model="mimo-v2-flash",
        base_url=None,
    )
    assert req.protocol == "anthropic"


def test_ai_test_passes_protocol_into_client(monkeypatch):
    calls = {}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            calls['init'] = {'args': args, 'kwargs': kwargs}

        def generate_with_instruction(self, *a, **k):
            return ("ok", {})

    # Patch the core client class so the router's runtime import picks it up
    import core.litellm_client as _llm_mod
    monkeypatch.setattr(_llm_mod, 'LiteLLMClient', DummyClient)

    # Simulate calling the router handler directly
    from web.backend.routers.users import test_ai_connection

    body = type('B', (), {
        'provider': 'mimo',
        'protocol': 'anthropic',
        'api_key': 'k',
        'model': 'mimo-v2-flash',
        'base_url': None,
    })

    # Call sync function (it's async but returns quickly)
    import asyncio
    res = asyncio.get_event_loop().run_until_complete(test_ai_connection(body, username='me', user='me'))

    # Assert DummyClient was constructed with provider_id and protocol
    assert 'init' in calls
    kw = calls['init']['kwargs']
    assert kw.get('provider_id') == 'mimo'
    assert kw.get('protocol') == 'anthropic'