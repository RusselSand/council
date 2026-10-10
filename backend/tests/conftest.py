import os
import shutil
import tempfile

import pytest

# Советы тестов — во временном каталоге, а не в .data репозитория. До первого get_store():
# хранилище читает каталог один раз на процесс.
DATA = tempfile.mkdtemp(prefix="council-tests-")
os.environ["COUNCIL_DATA"] = DATA
# Совет тестов — по умолчанию (Sol и Fable, судья Fable), что бы ни было в .env на машине:
# пустое значение в окружении сильнее .env и значит «по умолчанию».
for variable in ("COUNCIL_PARTICIPANT_1", "COUNCIL_PARTICIPANT_2", "COUNCIL_JUDGE"):
    os.environ[variable] = ""
# И без токена Figma: тесты не ходят в настоящую Figma, а ждут её только там, где подменили.
os.environ["FIGMA_TOKEN"] = ""
# Язык работы — по умолчанию, что бы ни стояло в .env.
os.environ["COUNCIL_LANGUAGE"] = ""
os.environ["COUNCIL_NOTES_LANGUAGE"] = ""

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
