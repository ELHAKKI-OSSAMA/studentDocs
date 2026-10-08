from app.worker.tasks import ping


def test_ping_task_logic():
    assert ping.run() == "pong"
