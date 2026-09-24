import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Vitest globals are off in this project's config, so Testing Library's
// auto-cleanup never registers itself. Register it globally here instead.
afterEach(cleanup);
