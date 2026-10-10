from fastapi import APIRouter

from ..config import MIN_PARTICIPANTS
from ..deps import AgentsDep, ConfigDep, FigmaDep, ProjectsDep, RepositoriesDep
from ..models import Settings
from ..projects import viewed

router = APIRouter(tags=["settings"])


@router.get("/settings")
def get_settings(config: ConfigDep, agents: AgentsDep, repositories: RepositoriesDep,
                 figma: FigmaDep, projects: ProjectsDep) -> Settings:
    available = agents.availability(m.alias for m in config.models)
    return Settings(
        models=[m.model_copy(update={"available": available[m.alias]}) for m in config.models],
        min_participants=MIN_PARTICIPANTS,
        default_participants=config.default_participants,
        default_judge=config.default_judge,
        repositories=str(repositories) if repositories else None,
        figma=figma is not None,
        projects=[viewed(project, repositories) for project in projects.list_projects()],
    )
