import { useState } from "react";
import ActivityList from "../components/ActivityList";
import GarminActivity from "../components/GarminActivity";
import GpxActivity from "../components/GpxActivity";
import SectionPage from "../components/SectionPage";
import type { components } from "../api/generated/schema";

type ActivitySection = "dashboard" | "garmin" | "gpx";

type Activity = components["schemas"]["ActivitySummary"];

const SECTIONS: Array<{ id: ActivitySection; label: string }> = [
    { id: "dashboard", label: "Dashboard" },
    { id: "garmin", label: "Garmin" },
    { id: "gpx", label: "GPX" },
];

interface ActivitiesPageProps {
    onStartSlideshow: (activity: Activity) => void;
}

export default function ActivitiesPage({ onStartSlideshow }: ActivitiesPageProps) {
    const [section, setSection] = useState<ActivitySection>("dashboard");

    return (
        <SectionPage
            title="Activities"
            sections={SECTIONS}
            selected={section}
            onSelect={(id) => setSection(id as ActivitySection)}
        >
            {section === "dashboard" ? (
                <ActivityList onSelect={onStartSlideshow} showDelete />
            ) : section === "garmin" ? (
                <GarminActivity />
            ) : (
                <GpxActivity />
            )}
        </SectionPage>
    );
}
