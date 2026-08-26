import { useRef } from "react";
import { Button } from "@mui/material";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import { useEvents } from "../events/EventContext";

export default function UploadButton() {
    const inputRef = useRef<HTMLInputElement | null>(null);
    const { setCategory, pushText } = useEvents();

    async function onChange(
        event: React.ChangeEvent<HTMLInputElement>
    ) {
        const files = Array.from(event.target.files ?? []);

        if (files.length === 0) {
            return;
        }

        setCategory("Upload", { current: 0, total: files.length, status: "active" });

        let uploaded = 0;
        let failed = false;

        for (const file of files) {
            const formData = new FormData();
            formData.append("file", file);

            const response = await fetch("./api/photos/upload", {
                method: "POST",
                body: formData,
            });

            if (response.ok) {
                uploaded++;
            } else {
                failed = true;
            }

            setCategory("Upload", { current: uploaded });
        }

        if (failed) {
            setCategory("Upload", { status: "failure" });
            pushText(`Upload failed (${uploaded}/${files.length})`, "error");
        } else {
            setCategory("Upload", { status: "success" });
            pushText(`Uploaded ${uploaded} file${uploaded === 1 ? "" : "s"}`);
        }

        event.target.value = "";
    }

    return (
        <>
            <input
                ref={inputRef}
                type="file"
                accept="image/*"
                multiple
                style={{ display: "none" }}
                onChange={onChange}
            />
            <Button
                variant="outlined"
                size="small"
                startIcon={<CloudUploadIcon />}
                onClick={() => inputRef.current?.click()}
                sx={{ m: 1 }}
            >
                Upload
            </Button>
        </>
    );
}
