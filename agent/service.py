from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI

from agent.config import Settings
from agent.model_client import RealModelClient
from agent.orchestrator import MoveAgent
from agent.schemas import AgentReply, AgentRequest
from agent.state import MoveStore
from agent.tools import CloseServiceTool

load_dotenv("/root/task/.env")
settings = Settings.from_environment()
store = MoveStore(settings.database_path)
model = RealModelClient(settings)
agent = MoveAgent(model, store, CloseServiceTool(store))
app = FastAPI(title="Utilities Move-Service Agent")


@app.post("/api/utilities/agent/move", response_model=AgentReply)
async def move_service(request: AgentRequest) -> AgentReply:
    return await agent.handle(request)
