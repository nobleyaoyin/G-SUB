"""Field-addressable request validation for the new draft API only."""
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

_STEPS = {
    "request_id": 1, "submission_type": 2, "title": 3, "running_head": 3,
    "abstract": 4, "keywords": 6, "corresponding_author": 7,
    "corresponding_author_position": 7, "coauthors": 8, "cover_letter": 9,
    "funding": 10, "manuscript_information": 10,
}


class SubmissionValidationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def wrapped(request: Request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                mapped = []
                for item in exc.errors():
                    parts = [str(part) for part in item.get("loc", ()) if part not in ("body", "payload")]
                    root = parts[0] if parts else "submission"
                    mapped.append({"step": _STEPS.get(root, 1), "field": ".".join(parts) or "submission", "message": item.get("msg", "Check this value.")})
                return JSONResponse(status_code=422, content={"detail": {"code": "submission_validation", "errors": mapped}}, headers={"Cache-Control": "no-store"})
        return wrapped
