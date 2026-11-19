"""全部跟随者离开后，实际CSR工作结束才归还租约和关闭映射。"""

import asyncio
from threading import Event

import pytest

from relationship_query.domain.path_budget import relation_query_budget
from relationship_query.infrastructure.member_index import MappedIntegers, MemberIndex
from relationship_query.infrastructure.member_traversal import MemberTraversalView
from relationship_query.runtime.admission import QueryAdmission
from relationship_query.services.query_plan import PersonPagePlan
from tests.test_member_index import make_index
from tests.test_query_admission import state


def test_cancel_all_waiters_drains_member_scan_before_mapping_close(tmp_path, monkeypatch):
    async def scenario():
        people = [f"p:expert:{i}" for i in range(1, 3000)]
        receipt, binding = make_index(tmp_path, people, [people])
        index = MemberIndex(tmp_path, receipt, binding)
        admission = QueryAdmission()
        entered, release = asyncio.Event(), Event()
        loop = asyncio.get_running_loop()
        original = MappedIntegers.__getitem__
        blocked = False
        closed_workspaces = []
        close = MemberTraversalView.close

        def read(mapped, position):
            nonlocal blocked
            if mapped is index.entity_people and not blocked:
                blocked = True
                loop.call_soon_threadsafe(entered.set)
                assert release.wait(2)
            return original(mapped, position)

        def close_workspace(view):
            close(view)
            closed_workspaces.append(view.closed)

        monkeypatch.setattr(MappedIntegers, "__getitem__", read)
        monkeypatch.setattr(MemberTraversalView, "close", close_workspace)

        def compute():
            view = MemberTraversalView(index, people[0], 4, relation_query_budget())
            try:
                return PersonPagePlan("v", 202611, people[0], "f", (), False, None)
            finally:
                view.close()

        try:
            owner = asyncio.create_task(admission.page_plan("same", compute))
            await entered.wait()
            follower = asyncio.create_task(admission.page_plan("same", compute))
            await state(admission, "followers", 1)
            owner.cancel()
            follower.cancel()
            for waiter in (owner, follower):
                with pytest.raises(asyncio.CancelledError):
                    await waiter
            assert admission.snapshot()["jobs"] == 1
            assert admission.snapshot()["heavy_active"] == 1
            closing = asyncio.create_task(admission.close())
            await asyncio.sleep(0)
            assert not closing.done() and not index.closed
            release.set()
            await closing
            assert closed_workspaces == [True]
            assert admission.snapshot()["jobs"] == admission.snapshot()["flights"] == 0
            assert admission.snapshot()["heavy_active"] == 0
        finally:
            release.set()
            await admission.close()
            index.close()
        assert all(mapped.mapping is None for mapped in index.arrays)

    asyncio.run(scenario())
