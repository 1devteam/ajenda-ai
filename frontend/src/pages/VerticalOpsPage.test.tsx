import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import VerticalOpsPage from "./VerticalOpsPage";
import { createVerticalTemplateMission } from "../api/client";
import type { CustomerSession, ProviderCredentialResponse, VerticalTemplate } from "../types";

const auth = vi.hoisted(() => ({ session: null as CustomerSession | null }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => auth }));
function template(id: string, action: string): VerticalTemplate {
  return {
    template_id: `vertical.${id}.v1`, role_key: `vertical.${id}`, pack_id: "vertical_ops.v1", pack_version: "1.0.0",
    display_name: `${id} plan`, description: "Plan description", objective_template: `Plan ${id}`,
    phase: "B", allows_runtime_queue: true, authority_class: "declarative", grants_execution_authority: false,
    steps: [{ step_key: id === "research" ? "research-internal" : "social-publish", action_name: action,
      title: id, description: id, depends_on: [], include_by_default: true, optional: false,
      side_effect_class: id === "research" ? "internal_read" : "external_publish", binding_status: "runtime_bound" }],
  };
}
const research = template("research", "web.research");
const social = template("social", "gtm.social_publish");
const credential: ProviderCredentialResponse = {
  credential_id: "social-publisher", tenant_id: "tenant-a", provider: "external_social", integration: "social",
  credential_type: "api_key", enabled: true, revoked: false, allowed_actions: ["gtm.social_publish"],
  allowed_side_effect_classes: ["external_publish"], trusted_destination_hosts: ["publisher.example.com"],
  uses_platform_master_key: false, created_at: "", updated_at: "",
};
let root: Root;
let container: HTMLDivElement;
let credentials: ProviderCredentialResponse[];
let posts: RequestInit[];
let create: (init: RequestInit) => Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  auth.session = { tenantId: "tenant-a", authMode: "api_key", apiKey: "test-key", phase: "operational" };
  credentials = [credential];
  posts = [];
  create = async (init) => json({ mission_id: "saved-mission", template_id: JSON.parse(String(init.body)).template_id, queued: false });
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    if (url.endsWith("/templates")) return json({ templates: [research, social] });
    if (url.endsWith("/provider-credentials")) return json({ credentials });
    if (url.endsWith("/vertical-ops/missions")) { posts.push(init); return create(init); }
    throw new Error(`Unexpected request: ${url}`);
  }));
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.unstubAllGlobals(); });
async function render(path = "/vertical-ops") {
  await act(async () => root.render(<MemoryRouter initialEntries={[path]}><VerticalOpsPage /></MemoryRouter>));
}
function article(name: string) {
  return [...container.querySelectorAll("article")].find((item) => item.querySelector("h2")?.textContent === `${name} plan`)!;
}
async function fill(scope: Element, label: string, value: string) {
  const element = [...scope.querySelectorAll("label")].find((item) => item.textContent?.startsWith(label))!
    .querySelector("input,textarea,select") as HTMLInputElement;
  const proto = element.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : element.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(element, value);
    element.dispatchEvent(new Event(element.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
  });
}
async function submit(scope: Element) {
  await act(async () => { scope.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
}

describe("vertical operations forms", () => {
  it("forces queue false even if a caller requests execution", async () => {
    await createVerticalTemplateMission(auth.session!, { template_id: research.template_id, queue: true });
    expect(JSON.parse(String(posts[0].body)).queue).toBe(false);
  });
  it("blocks blank research and sends a question through the authenticated non-queued API", async () => {
    await render();
    const form = article("research");
    expect(form.querySelector("button")!.disabled).toBe(true);
    await fill(form, "Research question", "   ");
    await submit(form);
    expect(posts).toHaveLength(0);
    await fill(form, "Research question", "Research Acme competitors");
    expect(form.querySelector("button")!.disabled).toBe(false);
    await submit(form);
    expect(JSON.parse(String(posts[0].body))).toMatchObject({ queue: false, selected_step_keys: ["research-internal"],
      step_inputs: { "research-internal": { query: "Research Acme competitors" } } });
    expect(new Headers(posts[0].headers).get("X-Tenant-Id")).toBe("tenant-a");
    expect(new Headers(posts[0].headers).get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
    expect(form.querySelector("a")!.getAttribute("href")).toBe("/vertical-ops?mission=saved-mission");
    await submit(form);
    expect(posts).toHaveLength(1);
  });
  it("sends Social content and a credential reference with stable action/HTTP keys on retry", async () => {
    create = async () => { throw new Error("connection dropped"); };
    await render();
    const form = article("social");
    await fill(form, "Post content", "Our update");
    await fill(form, "Platform", "twitter");
    await fill(form, "Publishing connection", "social-publisher");
    await submit(form);
    expect(form.textContent).toContain("Unable to reach");
    await submit(form);
    expect(posts).toHaveLength(2);
    expect(posts[1].body).toBe(posts[0].body);
    const key = new Headers(posts[0].headers).get("Idempotency-Key");
    expect(new Headers(posts[1].headers).get("Idempotency-Key")).toBe(key);
    expect(JSON.parse(String(posts[0].body))).toMatchObject({ queue: false,
      step_inputs: { "social-publish": { platform: "twitter", content: "Our update" } },
      idempotency_keys: { "social-publish": key },
      credential_references: { "social-publish": { schema_version: 1, credential_id: "social-publisher", provider: "external_social", credential_type: "api_key" } },
    });
    await fill(form, "Post content", "Revised update");
    await submit(form);
    expect(new Headers(posts[2].headers).get("Idempotency-Key")).not.toBe(key);
  });
  it("excludes wrong-tenant, read-only, revoked, disabled and incompatible connections", async () => {
    credentials = [
      { ...credential, tenant_id: "other" }, { ...credential, revoked: true }, { ...credential, enabled: false },
      { ...credential, provider: "external_read_provider", integration: "linkedin" },
      { ...credential, credential_type: "oauth" }, { ...credential, allowed_actions: ["provider.external_read"] },
      { ...credential, allowed_side_effect_classes: ["external_read"] },
    ];
    await render();
    const form = article("social");
    expect(form.querySelectorAll("option")).toHaveLength(1);
    expect(form.textContent).toContain("Self-service social publishing setup is not available yet");
    await fill(form, "Post content", "Hello");
    await fill(form, "Platform", "twitter");
    await submit(form);
    expect(posts).toHaveLength(0);
  });
  it("requires nonblank bounded Social content and platform", async () => {
    await render();
    const form = article("social");
    await fill(form, "Publishing connection", "social-publisher");
    for (const [content, platform] of [[" ", "twitter"], ["x".repeat(281), "twitter"], ["Hello", " "], ["Hello", "x".repeat(81)]]) {
      await fill(form, "Post content", content);
      await fill(form, "Platform", platform);
      await submit(form);
    }
    expect(posts).toHaveLength(0);
  });
  it("rejects oversized input and duplicate submits while a request is pending", async () => {
    let resolve!: (value: Response) => void;
    create = () => new Promise((done) => { resolve = done; });
    await render();
    const form = article("research");
    await fill(form, "Research question", "x".repeat(501));
    await submit(form);
    expect(posts).toHaveLength(0);
    await fill(form, "Research question", "Acme");
    await submit(form);
    await submit(form);
    expect(posts).toHaveLength(1);
    await act(async () => resolve(json({ mission_id: "saved", template_id: research.template_id, queued: false })));
  });
  it("drops drafts and credential selections on a tenant switch", async () => {
    await render();
    await fill(article("social"), "Post content", "Private tenant A content");
    await fill(article("social"), "Publishing connection", "social-publisher");
    auth.session = { ...auth.session!, tenantId: "tenant-b" };
    await render();
    expect(article("social").querySelector("textarea")!.value).toBe("");
    expect(article("social").querySelectorAll("option")).toHaveLength(1);
  });
  it("keeps Research usable when connection listing fails", async () => {
    vi.mocked(fetch).mockImplementation(async (url) => String(url).endsWith("/templates")
      ? json({ templates: [research, social] }) : json({ detail: "permission denied" }, 403));
    await render();
    expect(container.textContent).toContain("Publishing connections could not be loaded");
    await fill(article("research"), "Research question", "Acme");
    expect(article("research").querySelector("button")!.disabled).toBe(false);
    expect(article("social").querySelector("button")!.disabled).toBe(true);
  });
});
describe("saved plan review", () => {
  function saved(tenantId = "tenant-a") {
    return { mission: { mission_id: "saved", tenant_id: tenantId, objective: "Saved objective", status: "planned" },
      task_graph: { metadata: { template_id: research.template_id, allows_runtime_queue: true }, nodes: [
        { node_key: "research-internal", title: "Research", input_contract: { tool_input: { query: "Saved question" } } },
      ] } };
  }
  it("loads the persisted graph through GET only, including on a direct review URL", async () => {
    vi.mocked(fetch).mockResolvedValue(json(saved()));
    await render("/vertical-ops?mission=saved&execute=1");
    expect(container.textContent).toContain("Saved question");
    expect(container.textContent).toContain("Saved objective");
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetch).mock.calls[0][0]).toContain("/v1/missions/saved/lifecycle");
    expect(vi.mocked(fetch).mock.calls[0][1]?.method ?? "GET").toBe("GET");
    expect(container.querySelector("button")).toBeNull();
  });
  it("rejects a mismatched tenant response without rendering its data", async () => {
    vi.mocked(fetch).mockResolvedValue(json(saved("other")));
    await render("/vertical-ops?mission=saved");
    expect(container.textContent).toContain("does not belong");
    expect(container.textContent).not.toContain("Saved question");
  });
  it("ignores a late review response after switching workspaces", async () => {
    let resolve!: (response: Response) => void;
    vi.mocked(fetch).mockImplementationOnce(() => new Promise((done) => { resolve = done; }))
      .mockResolvedValueOnce(json({ detail: "mission not found for tenant" }, 404));
    await render("/vertical-ops?mission=saved");
    auth.session = { ...auth.session!, tenantId: "tenant-b" };
    await render("/vertical-ops?mission=saved");
    await act(async () => resolve(json(saved())));
    expect(container.textContent).toContain("mission not found for tenant");
    expect(container.textContent).not.toContain("Saved question");
  });
});
