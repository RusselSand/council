import os
import shutil
import tempfile

import pytest

# Советы тестов — во временном каталоге, а не в .data репозитория. До первого get_store():
# хранилище читает каталог один раз на процесс.
DATA = tempfile.mkdtemp(prefix="council-tests-")
os.environ["COUNCIL_DATA"] = DATA

from spec_council.app import app  # noqa: E402
from spec_council.deps import get_agents  # noqa: E402


class OfflineAgents:
    """Модели без входа. Тесты не зовут настоящие CLI: иначе /api/settings проверял бы вход
    в чью-то подписку и зависел бы от машины."""

    def availability(self, aliases, *, fresh=False):
        return dict.fromkeys(aliases, False)


@pytest.fixture(autouse=True)
def offline_models():
    app.dependency_overrides.setdefault(get_agents, OfflineAgents)
    yield
    app.dependency_overrides.pop(get_agents, None)


@pytest.fixture(scope="session", autouse=True)
def test_data():
    yield
    shutil.rmtree(DATA, ignore_errors=True)
