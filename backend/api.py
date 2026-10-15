"""FastAPI factory with injectable controller and a bounded shutdown lifespan."""
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Body, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from .engine import OutputTestWriteError


class OutputTestStart(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OutputTestSession(OutputTestStart):
    session_id: Annotated[str, Field(min_length=1)]


class OutputTestCommand(OutputTestSession):
    channel: Literal["acu1", "acu2", "water", "smoke", "temperature", "humidity", "door"]
    value: StrictBool

class SimulationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    temperature_c: Annotated[float | None, Field(ge=0, le=50, allow_inf_nan=False)] = None
    humidity_pct: Annotated[float | None, Field(ge=0, le=100, allow_inf_nan=False)] = None
    door_open: StrictBool = False
    smoke_alarm: StrictBool = False
    water_level_alarm: StrictBool = False


class ModeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: str


class AcuCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: str


def create_app(engine):
    @asynccontextmanager
    async def lifespan(app):
        try:
            engine.start()
            yield
        finally:
            engine.shutdown()

    app = FastAPI(title="acuPilot Backend", version="0.2.0", lifespan=lifespan)
    app.state.engine = engine

    @app.get("/api/status")
    def status():
        return engine.status()

    @app.get("/api/events")
    def events(limit: int = 50):
        try:
            return engine.event_store.events(limit) if engine.event_store else []
        except Exception as exc:
            raise HTTPException(503, "Event history unavailable") from exc

    @app.get("/api/settings")
    def settings():
        return engine.settings_contract()

    @app.patch("/api/settings")
    def patch_settings(data: dict = Body(...)):
        try:
            return engine.patch_settings(data)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, "Settings could not be persisted; no changes applied") from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    def test_mutation(operation, *args):
        try:
            return operation(*args)
        except OutputTestWriteError as exc:
            raise HTTPException(500, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/output-test/start")
    async def output_test_start(request: Request):
        try:
            OutputTestStart.model_validate_json(await request.body() or b"{}")
        except ValidationError as exc:
            raise HTTPException(422, "Start requires an empty body or empty object") from exc
        return test_mutation(engine.start_output_test)

    @app.post("/api/output-test/output")
    def output_test_output(data: OutputTestCommand):
        return test_mutation(engine.command_output_test, data.session_id, data.channel, data.value)

    @app.post("/api/output-test/heartbeat")
    def output_test_heartbeat(data: OutputTestSession):
        return test_mutation(engine.heartbeat_output_test, data.session_id)

    @app.post("/api/output-test/end")
    def output_test_end(data: OutputTestSession):
        return test_mutation(engine.end_output_test, data.session_id)

    @app.post("/api/mode")
    def mode(data: ModeUpdate):
        if data.mode not in ("auto", "manual", "pause"):
            raise HTTPException(400, "Allowed: auto, manual, pause")
        try:
            return engine.set_mode(data.mode)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/acu/{acu}/command")
    def command_acu(acu: int, data: AcuCommand):
        try:
            return engine.command_acu(acu, data.action)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/simulation")
    def simulation(data: SimulationUpdate):
        try:
            return engine.simulation_update(data.model_dump(exclude_unset=True))
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    return app
