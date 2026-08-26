import createClient from "openapi-fetch";
import type { paths } from "./generated/schema";

export const api = createClient<paths>({
    fetch: ((input: RequestInfo | URL, init?: RequestInit) => {
        if (input instanceof Request) {
            return fetch(new Request(input.url.replace(/^\//, ""), input));
        }
        return fetch(String(input).replace(/^\//, ""), init);
    }) as typeof fetch,
});