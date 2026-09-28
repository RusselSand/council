from fastapi import APIRouter

from ..config import MIN_PARTICIPANTS
from ..deps import ConfigDep
from ..models import Settings

router = APIRouter(tags=["settings"])


@router.get("/settings")
def get_settings(config: ConfigDep) -> Settings:
    return Settings(
        models=config.models,
        min_participants=MIN_PARTICIPANTS,
        default_participants=config.default_participants,
        default_judge=config.default_judge,
    )
