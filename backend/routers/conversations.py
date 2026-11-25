"""Start a conversation (PROJECT_SPEC §16 POST /conversations)."""

from fastapi import APIRouter, Depends

from auth.dependencies import AuthContext, require
from database.session import Database
from deps import get_db
from services import conversation_service

router = APIRouter(prefix="/api/conversations", tags=["query"])
CAN_QUERY = Depends(require("query:run"))


@router.post("", status_code=201)
def create_conversation(ctx: AuthContext = CAN_QUERY, db: Database = Depends(get_db)):
    with db.write() as conn:
        conversation = conversation_service.create_conversation(conn, ctx.user["id"])
    return {"id": conversation["id"], "created_at": conversation["created_at"]}
