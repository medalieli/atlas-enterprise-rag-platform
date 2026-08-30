from uuid import uuid4

import pytest

from app.api.enterprise import DemoRolePreviewRequest, change_demo_role
from app.auth import DemoRole, TrustedPrincipal
from app.core.config import Settings
from app.db.models import AuditEvent, Membership, MembershipRole


class RoleChangeSession:
    def __init__(self, owner: Membership) -> None:
        self.owner = owner
        self.added: list[object] = []
        self.committed = False

    async def scalar(self, _statement: object) -> Membership:
        return self.owner

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
@pytest.mark.parametrize("role", list(DemoRole))
async def test_owner_role_change_is_audited(
    monkeypatch: pytest.MonkeyPatch, role: DemoRole
) -> None:
    tenant_id, owner_id = uuid4(), uuid4()
    owner = Membership(
        id=uuid4(), tenant_id=tenant_id, user_id=owner_id, role=MembershipRole.OWNER
    )
    session = RoleChangeSession(owner)
    monkeypatch.setattr(
        "app.api.enterprise.get_settings",
        lambda: Settings(
            _env_file=None,
            app_env="test",
            demo_role_preview_enabled=True,
            demo_role_preview_secret="test-preview-secret-with-32-characters",
        ),
    )
    monkeypatch.setattr("app.api.enterprise.issue_demo_preview", lambda *_: "opaque")
    result = await change_demo_role(  # type: ignore[arg-type]
        DemoRolePreviewRequest(tenant_id=tenant_id, role=role),
        TrustedPrincipal(None, owner_id),
        session,
    )
    assert result.effective_role == role
    assert result.preview_token == "opaque"
    assert session.committed is True
    event = session.added[0]
    assert isinstance(event, AuditEvent)
    assert event.action == "demo.role.changed"
    assert event.actor_user_id == owner_id
    assert event.actor_role == "owner"
    assert event.event_metadata == {
        "new_role": role.value,
        "effective_demo_role": role.value,
    }
