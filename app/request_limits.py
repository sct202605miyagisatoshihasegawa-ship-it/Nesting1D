import os

from starlette import status
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


DEFAULT_MAX_REQUEST_BODY_BYTES = 262_144


def parse_max_request_body_bytes(value: str | None = None) -> int:
    """Parse the request body limit from an explicit value or the environment."""
    configured = os.getenv("MAX_REQUEST_BODY_BYTES") if value is None else value
    if configured is None or configured.strip() == "":
        return DEFAULT_MAX_REQUEST_BODY_BYTES

    text = configured.strip()
    if not all("0" <= character <= "9" for character in text):
        raise ValueError(
            "MAX_REQUEST_BODY_BYTES must be an integer greater than or equal to 1"
        )

    parsed = int(text)
    if parsed < 1:
        raise ValueError(
            "MAX_REQUEST_BODY_BYTES must be an integer greater than or equal to 1"
        )
    return parsed


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be greater than or equal to 1")
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = self._content_length(scope)
        if content_length is None:
            pass
        elif content_length < 0:
            await self._error_response(
                scope,
                receive,
                send,
                status.HTTP_400_BAD_REQUEST,
                "Invalid Content-Length",
            )
            return
        elif content_length > self.max_bytes:
            await self._error_response(
                scope,
                receive,
                send,
                status.HTTP_413_CONTENT_TOO_LARGE,
                "Request body too large",
            )
            return

        received_messages: list[Message] = []
        received_bytes = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue

            body_size = len(message.get("body", b""))
            if received_bytes + body_size > self.max_bytes:
                await self._error_response(
                    scope,
                    receive,
                    send,
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    "Request body too large",
                )
                return

            received_bytes += body_size
            received_messages.append(message)
            if not message.get("more_body", False):
                break

        next_message = 0

        async def replay_receive() -> Message:
            nonlocal next_message
            if next_message < len(received_messages):
                message = received_messages[next_message]
                next_message += 1
                return message
            return await receive()

        await self.app(scope, replay_receive, send)
    @staticmethod
    def _content_length(scope: Scope) -> int | None:
        values = [
            value
            for name, value in scope.get("headers", [])
            if name.lower() == b"content-length"
        ]
        if not values:
            return None
        if len(values) != 1:
            return -1

        value = values[0]
        if not value or not all(48 <= character <= 57 for character in value):
            return -1
        return int(value)

    @staticmethod
    async def _error_response(
        scope: Scope,
        receive: Receive,
        send: Send,
        status_code: int,
        detail: str,
    ) -> None:
        response = JSONResponse(
            {"detail": detail},
            status_code=status_code,
            headers={"Cache-Control": "no-store"},
        )
        await response(scope, receive, send)
