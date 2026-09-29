from fastapi import APIRouter, Request

from warden.models import QuestionLogEntry, SharingRule, SharingRulesResponse
from warden.state import get_store

router = APIRouter()


async def _current(request: Request) -> SharingRulesResponse:
    store = get_store(request)
    rule_rows = await store.sharing_rules.query()
    rules = [SharingRule.model_validate(r) for r in rule_rows]
    log_rows = sorted(
        await store.questions_log.query(), key=lambda r: str(r["asked_at"]), reverse=True
    )
    questions_log = [QuestionLogEntry.model_validate(r) for r in log_rows]
    return SharingRulesResponse(rules=rules, questions_log=questions_log)


@router.get("/api/sharing-rules")
async def get_sharing_rules(request: Request) -> SharingRulesResponse:
    return await _current(request)


@router.put("/api/sharing-rules")
async def put_sharing_rules(body: SharingRulesResponse, request: Request) -> SharingRulesResponse:
    store = get_store(request)
    # questions_log is read-only/server-maintained; only `rules` is replaced.
    for row in await store.sharing_rules.query():
        await store.sharing_rules.delete(row["peer_id"])
    for rule in body.rules:
        await store.sharing_rules.put(rule.peer_id, rule.model_dump(mode="json"))
    return await _current(request)
