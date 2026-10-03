"""Bound bodies before multipart parsing can spool oversized input to disk."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_file_size: int) -> None:
        self.app = app
        # Allow multipart headers/boundaries in addition to the actual file limit.
        self.upload_limit = max_file_size + 64 * 1024
        self.json_limit = 128 * 1024

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return
        upload = scope["path"].rstrip("/") == "/api/documents/upload"
        limit = self.upload_limit if upload else self.json_limit

        async def reject(status: int, code: str, message: str) -> None:
            await JSONResponse(
                status_code=status, content={"error": {"code": code, "message": message}}
            )(scope, receive, send)

        headers = dict(scope["headers"])
        if b"content-length" in headers:
            try:
                declared = int(headers[b"content-length"])
                if declared < 0:
                    raise ValueError
            except ValueError:
                await reject(400, "invalid_content_length", "Invalid Content-Length.")
                return
            if declared > limit:
                await reject(413, "request_too_large", "Request body exceeds the limit.")
                return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            block = message.get("body", b"")
            if len(body) + len(block) > limit:
                await reject(413, "request_too_large", "Request body exceeds the limit.")
                return
            body.extend(block)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
