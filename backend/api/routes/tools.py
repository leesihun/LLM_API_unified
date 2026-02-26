"""
Tools API endpoints
HTTP endpoints for external access to tools (RAG management, file listing, etc.)
Agent loop calls tools in-process; these endpoints are for direct API use.
"""
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from pydantic import BaseModel

from backend.utils.auth import get_optional_user, get_current_user
from backend.models.schemas import WebSearchRequest
from backend.core.llm_backend import llm_backend
from tools.web_search import WebSearchTool
from tools.python_coder import PythonCoderTool
from tools.rag import RAGTool
import config


router = APIRouter(prefix="/api/tools", tags=["tools"])


# ============================================================================
# Request/Response Schemas
# ============================================================================

class ToolResponse(BaseModel):
    success: bool
    answer: str
    data: Dict[str, Any]
    metadata: Dict[str, Any]
    error: Optional[str] = None


class PythonCoderRequest(BaseModel):
    instruction: str
    session_id: str
    timeout: Optional[int] = None


class RAGQueryRequest(BaseModel):
    query: str
    collection_name: str
    max_results: Optional[int] = None
    username: Optional[str] = None


class RAGCollectionRequest(BaseModel):
    collection_name: str


# ============================================================================
# Tool Endpoints
# ============================================================================

@router.get("/list")
def list_tools(current_user: Optional[dict] = Depends(get_optional_user)):
    return {
        "tools": [
            {"name": "websearch", "description": "Search the web for current information", "enabled": True},
            {"name": "python_coder", "description": "Execute coding tasks from natural language instructions", "enabled": True},
            {"name": "rag", "description": "Retrieve information from document collections", "enabled": True},
        ]
    }


@router.post("/websearch", response_model=ToolResponse)
async def websearch(request: WebSearchRequest, current_user: Optional[dict] = Depends(get_optional_user)):
    """Pure web search — returns raw Tavily results."""
    start_time = time.time()
    try:
        tool = WebSearchTool()
        search_result = tool.search(query=request.query, max_results=request.max_results)

        if not search_result["success"]:
            return ToolResponse(
                success=False, answer="", data={},
                metadata={"execution_time": time.time() - start_time},
                error=search_result.get("error", "Unknown error"),
            )

        return ToolResponse(
            success=True, answer="",
            data={"query": request.query, "results": search_result["results"], "num_results": search_result["num_results"]},
            metadata={"execution_time": time.time() - start_time},
        )
    except Exception as e:
        return ToolResponse(
            success=False, answer="", data={},
            metadata={"execution_time": time.time() - start_time}, error=str(e),
        )


@router.post("/python_coder", response_model=ToolResponse)
async def python_coder(request: PythonCoderRequest, current_user: Optional[dict] = Depends(get_optional_user)):
    """Execute a coding task from natural language instruction."""
    start_time = time.time()
    tool = None

    try:
        tool = PythonCoderTool(session_id=request.session_id)
    except Exception as e:
        return ToolResponse(
            success=False, answer=f"Tool initialization error: {e}",
            data={"stdout": "", "stderr": str(e), "files": {}, "workspace": "", "returncode": -1},
            metadata={"execution_time": time.time() - start_time}, error=str(e),
        )

    try:
        result = tool.execute(instruction=request.instruction, timeout=request.timeout)

        if result["success"]:
            answer = "Code executed successfully."
            if result['stdout']:
                answer += f"\n\nOutput:\n{result['stdout']}"
            if result.get('files'):
                answer += f"\n\nFiles in workspace: {', '.join(result['files'].keys())}"
        else:
            answer = "Code execution failed."
            if result['stdout']:
                answer += f"\n\nOutput (before error):\n{result['stdout']}"
            if result['stderr']:
                answer += f"\n\nError:\n{result['stderr']}"

        return ToolResponse(
            success=result["success"], answer=answer,
            data={
                "stdout": result["stdout"], "stderr": result["stderr"],
                "files": result["files"], "workspace": result["workspace"],
                "returncode": result["returncode"],
            },
            metadata={"execution_time": time.time() - start_time, "code_execution_time": result["execution_time"]},
            error=result.get("error"),
        )
    except Exception as e:
        return ToolResponse(
            success=False, answer=f"Unexpected execution error: {e}",
            data={"stdout": "", "stderr": str(e), "files": {}, "workspace": str(tool.workspace) if tool else "", "returncode": -1},
            metadata={"execution_time": time.time() - start_time}, error=str(e),
        )


@router.get("/python_coder/files/{session_id}")
async def list_python_files(session_id: str, current_user: Optional[dict] = Depends(get_optional_user)):
    try:
        tool = PythonCoderTool(session_id=session_id)
        files = tool.list_files()
        return {"success": True, "files": files, "error": None}
    except Exception as e:
        return {"success": False, "files": [], "error": str(e)}


@router.get("/python_coder/files/{session_id}/{filename}")
async def read_python_file(session_id: str, filename: str, current_user: Optional[dict] = Depends(get_optional_user)):
    try:
        tool = PythonCoderTool(session_id=session_id)
        content = tool.read_file(filename)
        if content is None:
            return {"success": False, "filename": filename, "content": "", "error": f"File '{filename}' not found"}
        return {"success": True, "filename": filename, "content": content, "error": None}
    except Exception as e:
        return {"success": False, "filename": filename, "content": "", "error": str(e)}


# ============================================================================
# RAG Management Endpoints
# ============================================================================

@router.post("/rag/collections", response_model=ToolResponse)
async def create_rag_collection(request: RAGCollectionRequest, current_user: dict = Depends(get_current_user)):
    username = current_user["username"]
    try:
        tool = RAGTool(username=username)
        result = tool.create_collection(request.collection_name)
        answer = f"Collection '{request.collection_name}' created." if result["success"] else f"Failed: {result.get('error', 'Unknown')}"
        return ToolResponse(success=result["success"], answer=answer, data=result, metadata={})
    except Exception as e:
        return ToolResponse(success=False, answer=str(e), data={}, metadata={}, error=str(e))


@router.get("/rag/collections")
async def list_rag_collections(current_user: dict = Depends(get_current_user)):
    tool = RAGTool(username=current_user["username"])
    return tool.list_collections()


@router.delete("/rag/collections/{collection_name}")
async def delete_rag_collection(collection_name: str, current_user: dict = Depends(get_current_user)):
    tool = RAGTool(username=current_user["username"])
    return tool.delete_collection(collection_name)


@router.post("/rag/upload")
async def upload_to_rag(
    collection_name: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Upload document to RAG collection."""
    import tempfile
    import os

    username = current_user["username"]

    try:
        tool = RAGTool(username=username)
        content = await file.read()
        file_ext = Path(file.filename).suffix.lower()

        binary_formats = ['.pdf', '.docx']
        if file_ext in binary_formats:
            with tempfile.NamedTemporaryFile(mode='wb', suffix=file_ext, delete=False) as tmp_file:
                tmp_file.write(content)
                tmp_path = tmp_file.name
            try:
                result = tool.upload_document(
                    collection_name=collection_name, document_path=tmp_path,
                    document_content=None, document_name=file.filename,
                )
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
        else:
            try:
                content_str = content.decode('utf-8')
            except UnicodeDecodeError:
                content_str = content.decode('latin-1')
            result = tool.upload_document(
                collection_name=collection_name, document_path=file.filename,
                document_content=content_str,
            )

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rag/collections/{collection_name}/documents")
async def list_rag_documents(collection_name: str, current_user: dict = Depends(get_current_user)):
    tool = RAGTool(username=current_user["username"])
    return tool.list_documents(collection_name)


@router.delete("/rag/collections/{collection_name}/documents/{document_id}")
async def delete_rag_document(collection_name: str, document_id: str, current_user: dict = Depends(get_current_user)):
    tool = RAGTool(username=current_user["username"])
    return tool.delete_document(collection_name, document_id)


@router.post("/rag/query", response_model=ToolResponse)
async def query_rag(request: RAGQueryRequest, current_user: Optional[dict] = Depends(get_optional_user)):
    """RAG query — retrieval + LLM synthesis (for direct API use, not agent loop)."""
    username = current_user["username"] if current_user else request.username or "guest"
    start_time = time.time()

    try:
        tool = RAGTool(username=username)
        final_max = request.max_results or config.RAG_MAX_RESULTS

        retrieval_result = tool.retrieve(
            collection_name=request.collection_name,
            query=request.query,
            max_results=final_max,
        )

        if not retrieval_result["success"]:
            return ToolResponse(
                success=False, answer="RAG retrieval failed", data={},
                metadata={"execution_time": time.time() - start_time},
                error=retrieval_result.get("error", "Unknown error"),
            )

        documents = retrieval_result.get("documents", [])
        score_key = "rerank_score" if any("rerank_score" in d for d in documents) else "score"
        docs_formatted = "\n\n".join([
            f"[Document {i+1}] Source: {doc['document']}, Chunk {doc['chunk_index']} (Score: {doc.get(score_key, 0):.2f}):\n{doc['chunk']}"
            for i, doc in enumerate(documents)
        ])

        prompt_path = config.PROMPTS_DIR / "tools" / "rag_synthesize.txt"
        if prompt_path.exists():
            with open(prompt_path, 'r', encoding='utf-8') as f:
                template = f.read()
            synthesis_prompt = template.format(
                user_query=request.query, documents=docs_formatted, context="Direct API query",
            )
        else:
            synthesis_prompt = f"Based on these documents:\n\n{docs_formatted}\n\nAnswer: {request.query}"

        from backend.core.llm_backend import llm_backend
        llm_response = await llm_backend.chat(
            [{"role": "user", "content": synthesis_prompt}],
            config.LLAMACPP_MODEL,
            config.TOOL_PARAMETERS.get("rag", {}).get("temperature", 0.5),
        )
        answer = llm_response.content or ""

        return ToolResponse(
            success=True, answer=answer,
            data={"query": request.query, "documents": documents, "num_results": len(documents)},
            metadata={"execution_time": time.time() - start_time, "collection": request.collection_name},
        )
    except Exception as e:
        return ToolResponse(
            success=False, answer=f"RAG query error: {e}", data={},
            metadata={"execution_time": time.time() - start_time}, error=str(e),
        )
