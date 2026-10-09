"""HTTP-ручки под /api. Новый раздел — новый модуль и одна строка include_router."""

from fastapi import APIRouter

from . import councils, documents, groups, settings, streams

API_PREFIX = "/api"

router = APIRouter(prefix=API_PREFIX)
router.include_router(councils.router)
router.include_router(groups.router)
router.include_router(settings.router)
router.include_router(streams.router)
router.include_router(documents.router)
