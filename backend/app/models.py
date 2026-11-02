"""Central import point so Alembic sees every ORM model."""

import importlib

# Domain modules that define ORM models are appended here as they are created.
MODEL_MODULES: list[str] = [
    "app.users.models",
    "app.academic.models",
    "app.students.models",
    "app.requests.models",
    "app.messages.models",
    "app.notifications.models",
    "app.documents.models",
    "app.audit.models",
    "app.emails.models",
    "app.ai.models",
    "app.mailconfig.models",
    "app.core.ephemeral",
]


def load_all_models() -> None:
    for module in MODEL_MODULES:
        importlib.import_module(module)
