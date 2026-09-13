"""Repository tests for :class:`InstallationRepository`.

Walks every :class:`BaseRepository` method in order: ``add``/``get``,
``find``/``count``/``exists``, ``update``, ``upsert``, then ``delete``
as the flow's cleanup. One session, one transaction — nothing commits.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import Column
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import async_session_maker
from app.models.installation import Installation
from app.repositories.installation import InstallationRepository


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with async_session_maker() as session:
        yield session


def _gh_id() -> int:
    return int(uuid4().hex[:8], 16) % 2147483647


def _new(*, gh_id: int, login: str, user_id: str) -> Installation:
    return Installation(
        user_id=user_id,
        github_installation_id=gh_id,
        account_login=login,
        account_type="Organization",
        repository_selection="all",
    )


async def test_installation_repository(session: AsyncSession) -> None:
    repo = InstallationRepository(session=session)
    user = f"repo-user-{uuid4().hex[:8]}"

    # add -----------------------------------------------------------------
    first = await repo.add(_new(gh_id=_gh_id(), login="login-a", user_id=user))
    second = await repo.add(_new(gh_id=_gh_id(), login="login-b", user_id=user))
    third = await repo.add(_new(gh_id=_gh_id(), login="login-c", user_id=user))
    await session.flush()

    print(f"first:{first.id} , second:{second.id} , third:{third.id}")
    assert first.id and second.id and third.id
    assert (await repo.get(first.id)) is not None
    assert (await repo.get("does-not-exist")) is None

    # find ----------------------------------------------------------------
    rows = await repo.find(
        col(repo.model.user_id) == user,
        order_by=col(repo.model.account_login),
    )
    assert [row.account_login for row in rows] == ["login-a", "login-b", "login-c"]

    page = await repo.find(
        col(repo.model.user_id) == user,
        order_by=col(repo.model.account_login),
        limit=1,
        offset=1,
    )
    assert [row.account_login for row in page] == ["login-b"]

    find_second = await repo.find(
        col(repo.model.github_installation_id) == second.github_installation_id,
        one=True,
    )
    assert find_second is not None
    assert find_second.id == second.id

    assert (await repo.count(col(repo.model.user_id) == user)) == 3
    assert (await repo.exists(col(repo.model.user_id) == user)) is True

    # update --------------------------------------------------------------
    created_at = second.created_at
    renamed = Installation(
        user_id=user,
        github_installation_id=second.github_installation_id,
        account_login="login-b-renamed",
        account_type="Organization",
        repository_selection="selected",
    )
    updated = await repo.update(
        col(repo.model.github_installation_id) == second.github_installation_id,
        values=renamed,
    )
    assert len(updated) == 1
    assert updated[0].id == second.id
    assert updated[0].account_login == "login-b-renamed"
    assert updated[0].created_at == created_at
    assert (
        await repo.update(col(repo.model.user_id) == "no-such-user", values=renamed)
    ) == []
    with pytest.raises(ValueError):
        await repo.update(values=renamed)

    # upsert --------------------------------------------------------------
    conflict_on = [col(repo.model.github_installation_id)]

    new_gh = _gh_id()

    insert_data = Installation(
        user_id=user,
        github_installation_id=new_gh,
        account_login="upsert-first",
        account_type="Organization",
        repository_selection="all",
    )

    inserted = await repo.upsert(
        values=insert_data,
        conflict_on=conflict_on,
    )

    assert inserted.account_login == "upsert-first"
    assert (await repo.count(col(repo.model.user_id) == user)) == 4

    print(
        f"upsert-first:{insert_data.github_installation_id}"
        f"account_login:{insert_data.account_login}"
    )

    upsert_data = Installation(
        user_id=user,
        github_installation_id=new_gh,
        account_login="upsert-second",
        account_type="User",
        repository_selection="selected,",
    )

    upserted = await repo.upsert(
        values=upsert_data,
        conflict_on=conflict_on,
    )

    print(
        f"upsert-second:{upserted.github_installation_id}"
        f"account_login:{upsert_data.account_login}"
    )

    assert upserted.id == inserted.id
    assert upserted.account_login == "upsert-second"
    assert upserted.created_at == inserted.created_at
    assert (await repo.count(col(repo.model.user_id) == user)) == 4

    # delete (cleanup) ----------------------------------------------------
    deleted = await repo.delete(col(repo.model.user_id) == user)
    assert len(deleted) == 4
    assert (await repo.count(col(repo.model.user_id) == user)) == 0
    assert (await repo.exists(col(repo.model.user_id) == user)) is False
    with pytest.raises(ValueError):
        await repo.delete()
