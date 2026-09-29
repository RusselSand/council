import pytest

from spec_council.app import app
from spec_council.deps import get_agents


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
