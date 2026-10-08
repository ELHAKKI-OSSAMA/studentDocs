async def test_live(client):
    res = await client.get("/health/live")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


async def test_ready_with_real_dependencies(client):
    res = await client.get("/health/ready")
    assert res.status_code == 200, res.text
    assert res.json() == {
        "status": "ok",
        "checks": {"database": "ok", "redis": "ok", "storage": "ok", "antivirus": "ok"},
    }


async def test_ready_reports_failure_without_leaking_details(make_settings, harness_for):
    broken = make_settings(
        database_url="postgresql+asyncpg://nobody:wrong@127.0.0.1:1/none",
        s3_bucket="bucket-that-does-not-exist",
        clamav_port=1,
    )
    async for h in harness_for(broken):
        async with h.client() as client:
            res = await client.get("/health/ready")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "degraded"
    assert body["checks"] == {"database": "fail", "redis": "ok", "storage": "fail", "antivirus": "fail"}
    assert "127.0.0.1" not in res.text and "wrong" not in res.text
