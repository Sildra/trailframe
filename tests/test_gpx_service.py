from __future__ import annotations

import allure
from sqlalchemy import select

from trailframe.models.activity import GpxActivity
from trailframe.services.activities.gpx_service import GpxService

_GPX = """
<gpx>
  <trk>
    <name>Trail</name>
    <trkseg>
      <trkpt lat="0.0" lon="0.0"><time>2023-06-01T08:00:00Z</time></trkpt>
      <trkpt lat="0.001" lon="0.001"><time>2023-06-01T08:00:30Z</time></trkpt>
    </trkseg>
  </trk>
</gpx>
"""


class TestSave:
    @allure.title("Saves a parsed GPX activity to the database")
    async def test_save_creates_activity(self, db_session):
        activity = await GpxService.save(_GPX, "trail.gpx")
        assert activity is not None
        assert activity.name == "Trail"
        assert activity.filename == "trail.gpx"
        assert activity.content_hash

        stored = (await db_session.execute(select(GpxActivity))).scalars().all()
        assert len(stored) == 1

    @allure.title("Deduplicates identical GPX content by content hash")
    async def test_save_dedupes_by_content_hash(self, db_session):
        first = await GpxService.save(_GPX, "a.gpx")
        second = await GpxService.save(_GPX, "b.gpx")
        assert first is not None and second is not None
        assert first.id == second.id

        stored = (await db_session.execute(select(GpxActivity))).scalars().all()
        assert len(stored) == 1

    @allure.title("Rejects invalid GPX without persisting anything")
    async def test_save_returns_none_for_invalid_gpx(self, db_session):
        assert await GpxService.save("not gpx", "bad.gpx") is None
        stored = (await db_session.execute(select(GpxActivity))).scalars().all()
        assert stored == []

    @allure.title("Lists stored GPX activities as summaries")
    async def test_list_summaries(self, db_session):
        await GpxService.save(_GPX, "trail.gpx")
        summaries = await GpxService.list_summaries()
        assert len(summaries) == 1
        assert summaries[0].filename == "trail.gpx"
        assert summaries[0].name == "Trail"
        assert summaries[0].duration == 30.0
