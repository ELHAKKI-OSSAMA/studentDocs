from fastapi import Query
from httpx import ASGITransport, AsyncClient

from app.core.errors import ConflictError
from app.main import create_app


def _app_with_probe_routes(settings):
    app = create_app(settings)

    @app.get("/_probe/conflict")
    async def conflict():
        raise ConflictError("Already exists", details={"field": "reference"})

    @app.get("/_probe/validated")
    async def validated(n: int = Query(ge=1)):
        return {"n": n}

    @app.get("/_probe/crash")
    async def crash():
        raise RuntimeError("database password is hunter2")

    return app


async def _get(settings, path, **kwargs):
    transport = ASGITransport(app=_app_with_probe_routes(settings), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path, **kwargs)


async def test_not_found_uses_error_envelope(settings):
    res = await _get(settings, "/does-not-exist")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"
    assert res.json()["error"]["request_id"] == res.headers["x-request-id"]


async def test_domain_error_envelope(settings):
    res = await _get(settings, "/_probe/conflict")
    assert res.status_code == 409
    assert res.json()["error"] == {
        "code": "conflict",
        "message": "Already exists",
        "details": {"field": "reference"},
        "request_id": res.headers["x-request-id"],
    }


async def test_validation_error_envelope(settings):
    res = await _get(settings, "/_probe/validated", params={"n": "0"})
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "validation_error"
    assert err["details"][0]["loc"] == ["query", "n"]


async def test_unhandled_error_does_not_leak_internals(settings):
    res = await _get(settings, "/_probe/crash")
    assert res.status_code == 500
    assert res.json()["error"]["code"] == "internal_error"
    assert "hunter2" not in res.text


async def test_request_id_propagation_and_security_headers(settings):
    res = await _get(settings, "/health/live", headers={"X-Request-ID": "abcdef12-3456"})
    assert res.headers["x-request-id"] == "abcdef12-3456"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"

    forged = await _get(settings, "/health/live", headers={"X-Request-ID": "<script>"})
    assert forged.headers["x-request-id"] != "<script>"
