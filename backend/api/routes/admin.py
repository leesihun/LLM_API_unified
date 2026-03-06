"""
Admin endpoints
/api/admin/model - Change default model
/api/admin/stop-inference - Control inference stop signal
"""
from fastapi import APIRouter, Depends

from backend.models.schemas import ChangeModelRequest
from backend.utils.auth import require_admin
from backend.utils.stop_signal import is_stop_requested, request_stop, clear_stop
import config

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/stop-inference")
def get_stop_status():
    """Check if the inference stop signal is active."""
    return {"stop_requested": is_stop_requested()}


@router.post("/stop-inference")
def stop_inference():
    """Activate the stop signal — halts all running agent loops at the next checkpoint."""
    request_stop()
    return {"status": "stop signal activated", "stop_requested": True}


@router.delete("/stop-inference")
def clear_stop_signal():
    """Deactivate the stop signal — allows inference to proceed."""
    clear_stop()
    return {"status": "stop signal cleared", "stop_requested": False}


@router.post("/model")
def change_model(
    request: ChangeModelRequest,
    admin: dict = Depends(require_admin)
):
    """
    Change the default model (admin only)
    Note: This updates the runtime config, not persistent storage
    """
    # Update the global config
    config.LLAMACPP_MODEL = request.model

    return {
        "status": "success",
        "message": f"Model changed to {request.model}",
        "model": request.model
    }
