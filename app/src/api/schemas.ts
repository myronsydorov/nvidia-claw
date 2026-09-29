import { z } from "zod";

// Mirrors warden/src/warden/models.py:HealthResponse (docs/CONTRACTS.md §3).
export const healthResponseSchema = z.object({
	status: z.literal("ok"),
	sandboxes_live: z.number().int(),
});

export type HealthResponse = z.infer<typeof healthResponseSchema>;
