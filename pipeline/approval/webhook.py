from __future__ import annotations

import hashlib
import hmac
import threading
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request, status

_SIGNATURE_HEADER = "x-hub-signature-256"
_SIGNATURE_PREFIX = "sha256="


class WebhookListener:
    def __init__(self, webhook_secret: str) -> None:
        self._secret = webhook_secret.encode("utf-8")
        self._merge_events: dict[int, threading.Event] = {}
        self._lock = threading.Lock()
        self._app = self._build_app()
        self._server_thread: threading.Thread | None = None

    def start(self, port: int) -> None:
        config = uvicorn.Config(
            app=self._app,
            host="0.0.0.0",
            port=port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        self._server_thread = threading.Thread(
            target=server.run,
            daemon=True,
            name="webhook-listener",
        )
        self._server_thread.start()

    def wait_for_pr_merge(self, pr_number: int, timeout: int = 3600) -> bool:
        event = threading.Event()
        with self._lock:
            self._merge_events[pr_number] = event
        merged = event.wait(timeout=timeout)
        with self._lock:
            self._merge_events.pop(pr_number, None)
        return merged

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="Pipeline Webhook Listener")

        @app.post("/webhook", status_code=status.HTTP_200_OK)
        async def receive_webhook(
            request: Request,
            x_hub_signature_256: str | None = Header(default=None, alias=_SIGNATURE_HEADER),
        ) -> dict:
            body = await request.body()
            self._verify_signature(body, x_hub_signature_256)
            payload: dict[str, Any] = await request.json()
            self._handle_payload(payload)
            return {"ok": True}

        return app

    def _verify_signature(self, body: bytes, signature_header: str | None) -> None:
        if not signature_header:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing signature header",
            )
        if not signature_header.startswith(_SIGNATURE_PREFIX):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Malformed signature header",
            )
        received = signature_header[len(_SIGNATURE_PREFIX):]
        expected = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(received, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )

    def _handle_payload(self, payload: dict[str, Any]) -> None:
        action = payload.get("action")
        pull_request = payload.get("pull_request", {})
        merged = pull_request.get("merged", False)
        pr_number = pull_request.get("number")

        if action == "closed" and merged and pr_number is not None:
            with self._lock:
                event = self._merge_events.get(pr_number)
            if event is not None:
                event.set()