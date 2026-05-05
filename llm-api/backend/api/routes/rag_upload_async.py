"""
Async RAG Upload Endpoint with Real-time Progress
Provides Server-Sent Events (SSE) for upload progress tracking
"""
import asyncio
import json
import tempfile
import os
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, Depends
from fastapi.responses import StreamingResponse
from backend.utils.auth import get_current_user
from tools.rag import RAGTool
import config


router = APIRouter(prefix="/api/rag", tags=["rag_async"])


async def upload_with_progress(
    collection_name: str,
    file: UploadFile,
    username: str
):
    """
    Generator that yields SSE progress updates during upload
    
    Yields:
        SSE-formatted progress events
    """
    import time
    
    # Read file content
    content = await file.read()
    file_ext = Path(file.filename).suffix.lower()
    
    # Save to temp file
    binary_formats = ['.pdf', '.docx']
    
    if file_ext in binary_formats:
        with tempfile.NamedTemporaryFile(
            mode='wb',
            suffix=file_ext,
            delete=False
        ) as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name
    else:
        # Text format - decode
        try:
            content_str = content.decode('utf-8')
        except UnicodeDecodeError:
            content_str = content.decode('latin-1')
        tmp_path = None
    
    try:
        tool = RAGTool(username=username)
        
        # Track progress
        progress_data = {"current": 0, "total": 100, "message": "Starting upload"}
        
        def progress_callback(message: str, progress_pct: float):
            """Callback to track progress"""
            progress_data["current"] = progress_pct
            progress_data["message"] = message
        
        # Yield initial progress
        yield f"data: {json.dumps(progress_data)}\n\n"
        
        # Start upload in thread pool (to allow progress updates)
        loop = asyncio.get_event_loop()
        
        if tmp_path:
            # Binary file upload
            def upload_task():
                return tool.upload_document(
                    collection_name=collection_name,
                    document_path=tmp_path,
                    document_content=None,
                    document_name=file.filename,
                    use_optimized=True  # Enable optimized uploader
                )
        else:
            # Text file upload
            def upload_task():
                return tool.upload_document(
                    collection_name=collection_name,
                    document_path=file.filename,
                    document_content=content_str,
                    use_optimized=False
                )
        
        # Run upload and periodically check progress
        upload_future = loop.run_in_executor(None, upload_task)
        
        while not upload_future.done():
            await asyncio.sleep(0.5)  # Check every 500ms
            
            # Yield progress update
            yield f"data: {json.dumps(progress_data)}\n\n"
        
        # Get result
        result = upload_future.result()
        
        # Yield final result
        result["progress"] = 100
        result["message"] = "Upload complete"
        yield f"data: {json.dumps(result)}\n\n"
        
    except Exception as e:
        error_data = {
            "success": False,
            "error": str(e),
            "progress": 100,
            "message": f"Upload failed: {str(e)}"
        }
        yield f"data: {json.dumps(error_data)}\n\n"
    
    finally:
        # Clean up temp file
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


@router.post("/upload/stream")
async def upload_to_rag_stream(
    collection_name: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload document to RAG collection with real-time progress updates
    
    Returns Server-Sent Events (SSE) stream with progress updates
    
    Usage (JavaScript):
    ```javascript
    const eventSource = new EventSource('/api/rag/upload/stream');
    eventSource.onmessage = (event) => {
        const progress = JSON.parse(event.data);
        console.log(progress.message, progress.current + '%');
    };
    ```
    """
    username = current_user["username"]
    
    return StreamingResponse(
        upload_with_progress(collection_name, file, username),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )
