import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from database import db, create_document, get_documents
from schemas import Tool

app = FastAPI(title="AI Toolbox API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "AI Toolbox Backend Running"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response

# --------------------
# AI Toolbox Endpoints
# --------------------

class CreateToolRequest(Tool):
    pass

class SearchResponse(BaseModel):
    results: List[Tool]
    total: int

@app.post("/api/tools", response_model=dict)
def add_tool(payload: CreateToolRequest):
    try:
        tool_id = create_document("tool", payload)
        return {"id": tool_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tools", response_model=List[Tool])
def list_tools(
    q: Optional[str] = Query(None, description="free text search across name, description, tags"),
    category: Optional[str] = Query(None),
    pricing: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200)
):
    try:
        mongo_filter = {}
        if category:
            mongo_filter["categories"] = {"$in": [category]}
        if pricing:
            mongo_filter["pricing"] = pricing
        # naive text search handled in Python after fetching (since no text index set here)
        docs = get_documents("tool", mongo_filter, limit=limit)
        tools: List[Tool] = []
        for d in docs:
            # convert Mongo _id to string-safe removal
            d.pop("_id", None)
            tools.append(Tool(**d))
        if q:
            q_lower = q.lower()
            tools = [t for t in tools if (
                q_lower in t.name.lower() or
                q_lower in t.description.lower() or
                any(q_lower in tag.lower() for tag in (t.tags or []))
            )]
        return tools
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/recommend", response_model=List[Tool])
def recommend_tools(
    task: str = Query(..., description="Describe what you want to do"),
    categories: Optional[List[str]] = Query(None, description="Optional categories to constrain"),
    budget: Optional[str] = Query(None, description="free, freemium, paid, open-source")
):
    try:
        # pull a larger sample then rank
        docs = get_documents("tool", {}, limit=200)
        items = []
        for d in docs:
            d.pop("_id", None)
            items.append(Tool(**d))
        # score heuristics based on keyword overlap
        t = task.lower()
        scored = []
        for tool in items:
            score = 0
            # name/desc match
            hay = f"{tool.name} {tool.description} {' '.join(tool.tags)} {' '.join(tool.use_cases)}".lower()
            for word in set(t.split()):
                if len(word) > 2 and word in hay:
                    score += 2
            # category boost
            if categories:
                if any(c.lower() in (cat.lower() for cat in tool.categories) for c in categories):
                    score += 3
                else:
                    score -= 1
            # budget alignment
            if budget and tool.pricing == budget:
                score += 2
            scored.append((score, tool))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [tool for score, tool in scored[:10]]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
