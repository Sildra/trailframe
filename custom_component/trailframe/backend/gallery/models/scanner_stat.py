from sqlmodel import Field, SQLModel


class ScannerStat(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    scanner: str = Field(index=True)
    count: int
    total_ms: float


class ScannerStatSummary(SQLModel):
    name: str
    items: int
    value: float
