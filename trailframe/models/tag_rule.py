from sqlmodel import JSON, Column, Field, SQLModel


class TagRule(SQLModel, table=True):
    """A user-defined rule that assigns tags to photos from their metadata.

    The rule body is stored as two JSON documents:

    - `conditions`: `{"operator": "and"|"or", "rules": [<condition>, ...]}` where a
      condition is `{"field": str, "operator": str, "value"?: Any, "match_label"?: str,
      "constraints"?: {metric: {op: value}}}`. See `TagRuleService` for the field catalog.
    - `tags`: the full tag paths the rule adds when it matches, e.g. `["Animals/Pet/Dog"]`.

    Rules only ever add tags; they never remove one.
    """

    __tablename__ = "tag_rule"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    enabled: bool = Field(default=True, index=True)
    priority: int = Field(default=0, index=True)
    description: str | None = None

    conditions: dict = Field(default_factory=dict, sa_column=Column(JSON))
    tags: list = Field(default_factory=list, sa_column=Column(JSON))
