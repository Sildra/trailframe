from sqlmodel import Field, SQLModel


class AppDataRecord(SQLModel, table=True):
    __tablename__ = "app_data"

    key: str = Field(primary_key=True)
    value: str = ""
    updated_at: str = ""
