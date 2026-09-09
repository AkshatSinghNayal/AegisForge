"""Bound request bytes before JSON construction, including chunked uploads."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from aegis_api.conventions import error_response


class ConfigurationBodyLimit:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return
        size = 0
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > 2 * 1024 * 1024:
                response = error_response(
                    413, "body_too_large", "Request must be at most 2 MiB."
                )
                response.headers["Cache-Control"] = "no-store"
                await response(scope, receive, send)
                return
            body.extend(message.get("body", b""))
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
