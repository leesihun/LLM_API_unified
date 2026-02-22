"""
OpenAI-compatible models endpoint
/v1/models
"""
from fastapi import APIRouter
import time

from backend.models.schemas import ModelsListResponse, ModelObject
from backend.core.llm_backend import llm_backend
import config

router = APIRouter(prefix="/v1", tags=["models"])


@router.get("/models", response_model=ModelsListResponse)
async def list_models():
    """List available models (OpenAI-compatible)"""
    try:
        model_names = await llm_backend.list_models()
        if not model_names:
            model_names = [config.LLAMACPP_MODEL]
    except Exception:
        model_names = [config.LLAMACPP_MODEL]

    models = [
        ModelObject(id=name, created=int(time.time()), owned_by="system")
        for name in model_names
    ]
    return ModelsListResponse(data=models)
