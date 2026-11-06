import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getLinkedInOAuthAuthorizeUrl,
  getMissionRuntimeTaskMaterialization,
  persistUiRuntimeInteraction,
} from "./client";
import type { CustomerSession } from "../types";

const session: CustomerSession = {
  authMode: "api_key",
  tenantId: "tenant-ui-trace",
  apiKey: "test-key-not-a-secret",
  keyId: "test-key",
  phase: "operational",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("UI runtime interaction transport", () => {
  it("reads persisted runtime task materialization without mutating the mission", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          mission_id: "mission-materialized",
          tenant_id: "tenant-ui-trace",
          materialization_status: "materialized",
          materialization_version: 1,
          created_execution_task_ids: ["task-1"],
          task_count: 1,
          blockers: [],
          warnings: [],
          updated_at: "2026-11-06T14:23:25Z",
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const materialization = await getMissionRuntimeTaskMaterialization(session, "mission-materialized");

    expect(materialization.materialization_status).toBe("materialized");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/v1/missions/mission-materialized/runtime-task-materialization");
    expect(init.method ?? "GET").toBe("GET");
    expect(new Headers(init.headers).get("X-Tenant-Id")).toBe("tenant-ui-trace");
  });

  it("sends bounded browser evidence and only opaque correlation identifiers to LinkedIn OAuth", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            schema_version: 1,
            event_id: "00000000-0000-0000-0000-000000000401",
            server_interaction_id: "00000000-0000-0000-0000-000000000402",
            acknowledgement: "persisted",
            persisted_at: "2026-10-21T00:00:00+00:00",
            duplicate: false,
          }),
          { status: 201 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            authorization_url: "https://provider.example.test/authorize",
            state: "opaque-provider-state",
            redirect_uri: "https://ajenda.example.test/credentials/linkedin/callback",
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    await persistUiRuntimeInteraction(session, {
      event_id: "00000000-0000-0000-0000-000000000401",
      local_interaction_id: "00000000-0000-0000-0000-000000000401",
      action_id: "credential.linkedin.oauth.connect",
      phase: "ui.action_clicked",
      producer_sequence: 1,
      occurred_at: "2026-10-21T00:00:00+00:00",
    });
    await getLinkedInOAuthAuthorizeUrl(session, "linkedin-read", {
      localInteractionId: "00000000-0000-0000-0000-000000000401",
      serverInteractionId: "00000000-0000-0000-0000-000000000402",
    });

    const [eventUrl, eventInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(eventUrl).toContain("/provider-credentials/runtime-interactions/events");
    expect(JSON.parse(String(eventInit.body))).toEqual({
      event_id: "00000000-0000-0000-0000-000000000401",
      local_interaction_id: "00000000-0000-0000-0000-000000000401",
      action_id: "credential.linkedin.oauth.connect",
      phase: "ui.action_clicked",
      producer_sequence: 1,
      occurred_at: "2026-10-21T00:00:00+00:00",
    });

    const [authorizeUrl, authorizeInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    const headers = new Headers(authorizeInit.headers);
    expect(authorizeUrl).toContain("/provider-credentials/linkedin/oauth/authorize-url");
    expect(headers.get("X-Ajenda-UI-Local-Interaction-Id")).toBe("00000000-0000-0000-0000-000000000401");
    expect(headers.get("X-Ajenda-UI-Interaction-Id")).toBe("00000000-0000-0000-0000-000000000402");
    expect(headers.get("X-Tenant-Id")).toBe("tenant-ui-trace");
    expect(headers.get("X-Api-Key")).toBe("test-key-not-a-secret");
    expect(JSON.stringify(authorizeInit)).not.toContain("opaque-provider-state");
  });
});
