import createClient from "openapi-fetch";
import type { paths } from "./generated/schema";

const baseUrl = new URL(".", window.location.href).href;

export const api = createClient<paths>({ baseUrl });