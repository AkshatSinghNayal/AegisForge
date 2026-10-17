"""Bound request bytes before JSON construction, including chunked uploads."""

import asyncio

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from aegis_api.conventions import error_response

BODY_TIMEOUT_SECONDS = 15
MAX_BODY = 2 * 1024 * 1024


class ConfigurationBodyLimit:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        if headers.get(b"content-encoding", b"identity").lower() != b"identity":
            await error_response(
                415,
                "encoding_unsupported",
                "Compressed request bodies are not accepted.",
            )(scope, receive, send)
            return
        body = bytearray()
        try:
            async with asyncio.timeout(BODY_TIMEOUT_SECONDS):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > MAX_BODY:
                        response = error_response(
                            413, "body_too_large", "Request must be at most 2 MiB."
                        )
                        response.headers["Cache-Control"] = "no-store"
                        await response(scope, receive, send)
                        return
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await error_response(
                408, "body_timeout", "Request body deadline exceeded."
            )(scope, receive, send)
            return

        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
