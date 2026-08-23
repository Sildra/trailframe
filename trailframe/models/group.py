from datetime import date

from sqlmodel import Field, SQLModel


class PhotoGroup(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    start_date: date | None = None
    end_date: date | None = None


class PhotoGroupSummary(SQLModel):
    id: int | None = None
    name: str
    start_date: date | None = None
    end_date: date | None = None
    automatic: bool = False
    photo_ids: list[int] = Field(default_factory=list)
