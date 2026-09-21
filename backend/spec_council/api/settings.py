from fastapi import APIRouter

from ..deps import ConfigDep
from ..models import Settings

router = APIRouter(tags=["settings"])


@router.get("/settings")
def get_settings(config: ConfigDep) -> Settings:
    return Settings(
        models=config.models,
        default_author=config.default_author,
        default_reviewer=config.default_reviewer,
    )
