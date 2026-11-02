from __future__ import annotations

from typing import Any

from sqlmodel import select

from trailframe.models.tag import Tag

from .base import MigrationPlan

PERCENT_METRICS = frozenset({"confidence", "surface"})


class InitializeMigration(MigrationPlan):
    name = "initialize_migration"
    min_version = "0.0.0"
    max_version = "9999.0.0"
    description = "Initialize migration"

    async def run(self, session) -> None:
        pass


def _scale_metric(metric: Any) -> Any:
    """Turn a stored 0..1 metric value into percent, leaving already-scaled values alone."""
    if not isinstance(metric, dict) or metric.get("name") not in PERCENT_METRICS:
        return metric

    value = metric.get("value")

    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        return metric

    return {**metric, "value": round(value * 100, 10)}


def _scale_condition(condition: Any) -> Any:
    if not isinstance(condition, dict):
        return condition

    if condition.get("type") == "detection":
        return {**condition, "metrics": [_scale_metric(metric) for metric in condition.get("metrics") or []]}

    if condition.get("type") == "group":
        return {**condition, "conditions": [_scale_condition(child) for child in condition.get("conditions") or []]}

    return condition


class RuleMetricsPercent(MigrationPlan):
    """Rules now write detection metrics in percent instead of a 0..1 fraction."""

    name = "rule_metrics_percent"
    min_version = "0.0.0"
    max_version = "9999.0.0"
    description = "Convert stored detection metrics to percent"

    async def run(self, session) -> None:
        result = await session.execute(select(Tag))
        changed = False

        for tag in result.scalars():
            rules = tag.rules or []
            converted = []

            for rule in rules:
                if not isinstance(rule, dict) or not isinstance(rule.get("definition"), dict):
                    converted.append(rule)
                    continue

                definition = rule["definition"]
                conditions = [_scale_condition(condition) for condition in definition.get("conditions") or []]
                converted.append({**rule, "definition": {**definition, "conditions": conditions}})

            if converted != rules:
                tag.rules = converted
                session.add(tag)
                changed = True

        if changed:
            await session.commit()


MIGRATION_PLANS: tuple[MigrationPlan, ...] = (InitializeMigration(), RuleMetricsPercent())
