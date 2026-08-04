import asyncio
from types import SimpleNamespace

from core.permissions import InputSource, PermissionPolicy
from core.security import UpfrontApprovalGate, has_explicit_upfront_approval
from core.tools import RiskLevel, ToolDefinition, ToolExecutor, ToolRegistry

SCHEMA = {
    "type": "OBJECT",
    "properties": {"action": {"type": "STRING"}},
    "required": ["action"],
}


class UI:
    microphone_enabled = False

    def __init__(self):
        self.logs = []

    def set_state(self, _state):
        pass

    def write_log(self, value):
        self.logs.append(value)


def _jarvis(definition):
    from core.security import VoiceConfirmationGate
    from main import JarvisLive

    jarvis = JarvisLive.__new__(JarvisLive)
    jarvis.ui = UI()
    jarvis._pending_confirmation_fc = None
    jarvis._pending_confirmation_source = None
    jarvis._pending_confirmation_context = None
    jarvis._confirmation_execution_scheduled = False
    jarvis._confirmed_replay_cache = {}
    jarvis._denied_replay_cache = {}
    jarvis._active_input_source = InputSource.LOCAL
    jarvis._remote_drive_folders = set()
    jarvis._confirmation_gate = VoiceConfirmationGate()
    jarvis._upfront_approval_gate = UpfrontApprovalGate()
    jarvis.tool_registry = ToolRegistry([definition])
    jarvis.tool_executor = ToolExecutor(jarvis.tool_registry)
    jarvis.permission_policy = PermissionPolicy()
    jarvis.request_audit = None
    jarvis._loop = None
    jarvis.session = None
    return jarvis


def test_upfront_approval_detection_rejects_explicit_denial():
    assert has_explicit_upfront_approval("Te autorizo, hacelo de una")
    assert has_explicit_upfront_approval("Proceed without asking me again")
    assert not has_explicit_upfront_approval("No te autorizo a hacerlo")


def test_upfront_approval_is_bound_to_source_and_consumed_once():
    gate = UpfrontApprovalGate()
    assert gate.observe_request("Confirmo de una", InputSource.UI)
    assert not gate.consume(InputSource.DASHBOARD_TEXT)
    assert gate.consume(InputSource.UI)
    assert not gate.consume(InputSource.UI)


def test_new_non_approved_request_clears_stale_bundled_approval():
    gate = UpfrontApprovalGate()
    assert gate.observe_request("Te autorizo de una", InputSource.UI)
    assert not gate.observe_request("Ahora sólo mostrámelo", InputSource.UI)
    assert not gate.consume(InputSource.UI)


def test_bundled_approval_executes_non_destructive_action_without_staging():
    calls = []
    definition = ToolDefinition(
        "code_helper", "write", SCHEMA,
        handler=lambda args: calls.append(args) or "written",
        risk=RiskLevel.SENSITIVE,
    )
    jarvis = _jarvis(definition)
    jarvis._upfront_approval_gate.observe_request(
        "Escribilo, te autorizo de una", InputSource.LOCAL
    )
    response = asyncio.run(jarvis._execute_tool(SimpleNamespace(
        name="code_helper", args={"action": "write"}, id="call-write"
    )))
    assert response.response["success"] is True
    assert len(calls) == 1
    assert jarvis._pending_confirmation_fc is None


def test_deletion_requires_fresh_confirmation_even_with_bundled_approval():
    calls = []
    definition = ToolDefinition(
        "file_controller", "delete", SCHEMA,
        handler=lambda args: calls.append(args) or "deleted",
        risk=RiskLevel.SENSITIVE,
    )
    jarvis = _jarvis(definition)
    jarvis._upfront_approval_gate.observe_request(
        "Borrá el archivo, te autorizo de una", InputSource.LOCAL
    )
    response = asyncio.run(jarvis._execute_tool(SimpleNamespace(
        name="file_controller", args={"action": "delete"}, id="call-delete"
    )))
    assert "VOICE_CONFIRMATION_REQUIRED" in response.response["result"]
    assert calls == []
    assert jarvis._pending_confirmation_fc is not None


def test_model_retry_after_confirmed_execution_is_not_executed_twice():
    from core.request_context import RequestContext

    calls = []
    definition = ToolDefinition(
        "code_helper", "write", SCHEMA,
        handler=lambda args: calls.append(args) or "written",
        risk=RiskLevel.SENSITIVE,
    )
    jarvis = _jarvis(definition)
    jarvis.session = None
    jarvis._confirmation_execution_scheduled = True
    fc = SimpleNamespace(
        name="code_helper", args={"action": "write"}, id="call-original"
    )
    jarvis._pending_confirmation_fc = fc
    jarvis._pending_confirmation_source = InputSource.LOCAL
    jarvis._pending_confirmation_context = RequestContext.create(
        InputSource.LOCAL, tool_call_id=fc.id
    )

    asyncio.run(jarvis._execute_confirmed_pending())
    retry = asyncio.run(jarvis._execute_tool(SimpleNamespace(
        name="code_helper", args={"action": "write"}, id="call-retry"
    )))

    assert len(calls) == 1
    assert retry.response["duplicate_suppressed"] is True
    assert "VOICE_CONFIRMATION_REQUIRED" not in retry.response["result"]


def test_natural_denial_clears_pending_and_suppresses_model_retry():
    calls = []
    definition = ToolDefinition(
        "reminder", "Set reminder", SCHEMA,
        handler=lambda args: calls.append(args) or "scheduled",
        risk=RiskLevel.EXTERNAL_EFFECT,
    )
    jarvis = _jarvis(definition)
    fc = SimpleNamespace(
        name="reminder",
        args={"action": "set"},
        id="call-reminder",
    )

    staged = asyncio.run(jarvis._execute_tool(fc))
    assert "VOICE_CONFIRMATION_REQUIRED" in staged.response["result"]
    assert jarvis._handle_confirmation_text(
        "No, no quiero poner el recordatorio"
    )
    assert jarvis._pending_confirmation_fc is None

    retry = asyncio.run(jarvis._execute_tool(SimpleNamespace(
        name="reminder",
        args={"action": "set"},
        id="call-reminder-retry",
    )))

    assert calls == []
    assert retry.response["error"] == "confirmation_denied"
    assert retry.response["duplicate_suppressed"] is True
    assert "VOICE_CONFIRMATION_REQUIRED" not in retry.response["result"]

    jarvis._observe_upfront_approval(
        "Ahora sí quiero ese recordatorio",
        InputSource.LOCAL,
    )
    new_request = asyncio.run(jarvis._execute_tool(SimpleNamespace(
        name="reminder",
        args={"action": "set"},
        id="call-reminder-new-request",
    )))
    assert "VOICE_CONFIRMATION_REQUIRED" in new_request.response["result"]


def test_local_screen_inspection_is_read_only_and_never_prompts():
    definition = ToolDefinition(
        "screen_process", "Inspect screen", SCHEMA,
        handler=None,
        risk=RiskLevel.READ_ONLY,
        special=True,
    )
    decision = PermissionPolicy().evaluate(
        definition,
        {"action": "screen"},
    )

    assert decision.allowed
    assert not decision.requires_confirmation
