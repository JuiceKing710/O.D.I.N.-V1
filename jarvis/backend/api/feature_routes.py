"""Routes for new features: RAG, tool management, and structured outputs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Depends

from jarvis.backend.core.app_factory import (
    get_rag_engine,
    get_tool_registry,
    get_constrained_generator,
    get_performance_monitor,
)


router = APIRouter(prefix="/api/v1", tags=["features"])


# ============================================================================
# RAG Endpoints
# ============================================================================


@router.post("/rag/ingest", summary="Ingest text into RAG")
async def rag_ingest(
    text: str,
    source_id: str,
    metadata: dict[str, Any] | None = None,
    rag_engine=Depends(get_rag_engine),
) -> dict[str, Any]:
    """Ingest text into the RAG vector store."""
    try:
        chunk_count = rag_engine.ingest_text(text, source_id, metadata=metadata)
        return {
            "ok": True,
            "source_id": source_id,
            "chunks_ingested": chunk_count,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/rag/search", summary="Search RAG documents")
async def rag_search(
    query: str,
    top_k: int = 5,
    rag_engine=Depends(get_rag_engine),
) -> dict[str, Any]:
    """Search for relevant documents in RAG store."""
    try:
        results = rag_engine.query(query, top_k=top_k)
        return {
            "ok": True,
            "query": query,
            "results": [
                {
                    "content": r.content,
                    "source": r.source,
                    "score": r.score,
                }
                for r in results
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/rag/delete", summary="Delete RAG source")
async def rag_delete(
    source_id: str,
    rag_engine=Depends(get_rag_engine),
) -> dict[str, Any]:
    """Delete all documents from a source."""
    try:
        rag_engine.delete_source(source_id)
        return {
            "ok": True,
            "source_id": source_id,
            "deleted": True,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ============================================================================
# Tool Management Endpoints
# ============================================================================


@router.get("/tools/list", summary="List available tools")
async def list_tools(
    tool_registry=Depends(get_tool_registry),
) -> dict[str, Any]:
    """List all registered tools."""
    tools = tool_registry.list()
    return {
        "ok": True,
        "tools": [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ],
    }


@router.get("/tools/{tool_id}", summary="Get tool definition")
async def get_tool(
    tool_id: str,
    tool_registry=Depends(get_tool_registry),
) -> dict[str, Any]:
    """Get detailed definition of a tool."""
    tool = tool_registry.find(tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_id}")
    return {
        "ok": True,
        "tool": {
            "id": tool.id,
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
            "output_schema": tool.output_schema,
        },
    }


# ============================================================================
# Performance Monitoring Endpoints
# ============================================================================


@router.get("/performance/stats", summary="Get inference performance stats")
async def get_performance_stats(
    performance_monitor=Depends(get_performance_monitor),
) -> dict[str, Any]:
    """Get recent inference performance statistics."""
    stats = performance_monitor.recent_stats(n=10)
    suggestions = performance_monitor.suggest_optimizations()
    return {
        "ok": True,
        "stats": stats,
        "suggestions": suggestions,
    }


# ============================================================================
# Structured Output Endpoints
# ============================================================================


@router.post("/chat/structured", summary="Structured response endpoint")
async def structured_chat(
    text: str,
    schema: str = "diagnostic_report",
    constrained_gen=Depends(get_constrained_generator),
) -> dict[str, Any]:
    """Request a structured JSON response (requires compatible model)."""
    if schema not in ["diagnostic_report", "memory_fact"]:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown schema: {schema}. Supported: diagnostic_report, memory_fact",
        )
    return {
        "ok": True,
        "schema": schema,
        "message": "Structured response requested. This feature requires model support for JSON output.",
        "note": "Enable this in Settings → Features → Structured Outputs",
    }
