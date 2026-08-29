import { useEffect, useState } from "react";
import {
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Typography,
} from "@mui/material";
import { api } from "../api/client";
import ActivityList from "../components/ActivityList";
import CustomSlideshowMenu from "../components/CustomSlideshowMenu";
import SectionPage from "../components/SectionPage";
import type { MenuSection } from "../lib/slideshowSections";
import type { components } from "../api/generated/schema";
import type { SlideshowSource } from "./SlideshowPage";

const SECTIONS: Array<{ id: MenuSection; label: string }> = [
    { id: "activities", label: "Activities" },
    { id: "groups", label: "Groups" },
    { id: "custom", label: "Custom" },
];

type PhotoGroupSummary = components["schemas"]["PhotoGroupSummary"];

interface GroupListProps {
    onStart: (name: string, photoIds: number[]) => void;
}

function formatPeriod(group: PhotoGroupSummary): string {
    if (!group.start_date && !group.end_date) {
        return "-";
    }

    return [group.start_date, group.end_date].filter(Boolean).join(" → ");
}

function GroupList({ onStart }: GroupListProps) {
    const [groups, setGroups] = useState<PhotoGroupSummary[]>([]);

    useEffect(() => {
        let cancelled = false;

        api.GET("/api/photos/groups")
            .then(({ data, error }) => {
                if (!cancelled && !error && data) {
                    setGroups(data);
                }
            })
            .catch(() => {});

        return () => {
            cancelled = true;
        };
    }, []);

    if (groups.length === 0) {
        return <Typography color="text.secondary">No groups yet.</Typography>;
    }

    const start = (group: PhotoGroupSummary) => onStart(group.name, group.photo_ids ?? []);

    return (
        <TableContainer>
            <Table size="small">
                <TableHead>
                    <TableRow>
                        <TableCell>Name</TableCell>
                        <TableCell>Period</TableCell>
                        <TableCell>Photos</TableCell>
                    </TableRow>
                </TableHead>
                <TableBody>
                    {groups.map((group) => (
                        <TableRow
                            key={`${group.automatic}:${group.id ?? group.name}`}
                            hover
                            tabIndex={0}
                            onClick={() => start(group)}
                            onKeyDown={(event) => {
                                if (event.key === "Enter") {
                                    start(group);
                                }
                            }}
                            sx={{ cursor: "pointer" }}
                        >
                            <TableCell>{group.name}</TableCell>
                            <TableCell>{formatPeriod(group)}</TableCell>
                            <TableCell>{group.photo_ids?.length ?? 0}</TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </TableContainer>
    );
}

interface SlideshowMenuPageProps {
    section: MenuSection;
    onSectionChange: (section: MenuSection) => void;
    onStartSlideshow: (source: SlideshowSource) => void;
}

export default function SlideshowMenuPage({ section, onSectionChange, onStartSlideshow }: SlideshowMenuPageProps) {
    return (
        <SectionPage
            title="Slideshow"
            sections={SECTIONS}
            selected={section}
            onSelect={(id) => onSectionChange(id as MenuSection)}
        >
            {section === "activities" ? (
                <ActivityList onSelect={(activity) => onStartSlideshow({ kind: "activity", activity })} />
            ) : section === "groups" ? (
                <GroupList
                    onStart={(name, photoIds) => onStartSlideshow({ kind: "group", name, photoIds })}
                />
            ) : (
                <CustomSlideshowMenu
                    onStart={(name, photoIds, useThumbnails, controls, map) =>
                        onStartSlideshow({
                            kind: "group",
                            name,
                            photoIds,
                            thumbnails: useThumbnails,
                            controls,
                            map,
                        })
                    }
                />
            )}
        </SectionPage>
    );
}
