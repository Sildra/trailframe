from sqlmodel import JSON, Column, Field, SQLModel


class Tag(SQLModel, table=True):
    """A node of the hierarchical tag registry.

    `path` is the canonical, slash-separated full path of the tag
    ("Architecture/Building/Church"); `name` is its last segment. `parent_id`
    links to the parent node so the tree can be walked without parsing paths.
    """

    __tablename__ = "tags"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    path: str = Field(index=True, unique=True)
    parent_id: int | None = Field(default=None, index=True)
    depth: int = Field(default=0)
    rules: list[dict] = Field(default_factory=list, sa_column=Column(JSON))


class TagNode(SQLModel):
    """A registry tag with its children, as returned by the API."""

    id: int | None = None
    name: str
    path: str
    depth: int = 0
    count: int = 0
    """Photos tagged with exactly this path."""
    total: int = 0
    """Photos tagged with this path or any of its descendants."""
    rules_count: int = 0
    children: list["TagNode"] = Field(default_factory=list)


TagNode.model_rebuild()
