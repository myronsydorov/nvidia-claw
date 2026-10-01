"""Typed access to app.state, which FastAPI/Starlette otherwise expose as Any."""

from fastapi import Request

from warden.db import Store
from warden.events import EventBus
from warden.reassurance.service import Reassurance
from warden.sandbox.driver import SandboxDriver


def get_store(request: Request) -> Store:
    store: Store = request.app.state.store
    return store


def get_events(request: Request) -> EventBus:
    events: EventBus = request.app.state.events
    return events


def get_driver(request: Request) -> SandboxDriver:
    driver: SandboxDriver = request.app.state.driver
    return driver


def get_reassurance(request: Request) -> Reassurance:
    reassurance: Reassurance = request.app.state.reassurance
    return reassurance
