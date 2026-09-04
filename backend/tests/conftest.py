import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("IRIS_LOG_LEVEL", "warning")


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "iris-data"
    d.mkdir()
    return d


@pytest.fixture()
def app(data_dir):
    from iris.main import create_app

    application = create_app(data_dir=data_dir, token="test-token", use_keyring=False, enable_tts=False)
    yield application
    application.state.ctx.close()


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as c:
        yield c


@pytest.fixture()
def client_sans_jeton(app):
    """Client sans jeton : sert à vérifier que les accès restent bien refusés."""
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c
