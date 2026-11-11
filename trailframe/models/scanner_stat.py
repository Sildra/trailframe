from sqlmodel import Field, SQLModel


class ScannerStat(SQLModel, table=True):
    __tablename__ = "scanner_stats"

    id: int | None = Field(default=None, primary_key=True)
    scanner: str = Field(unique=True)
    count: int
    total_ms: float


class ScannerStatSummary(SQLModel):
    name: str
    items: int
    value: float
