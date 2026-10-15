"""Reject every WebSocket handshake redirect before account subscriptions."""
from websockets.asyncio.client import connect as SDKConnect


class connect(SDKConnect):
    def process_redirect(self, exc):
        return exc
