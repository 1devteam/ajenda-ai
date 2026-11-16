import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { EmailReferences } from "./EmailReferences";

describe("email reference readback", () => {
  it("labels references honestly and escapes provider data", () => {
    const html = renderToStaticMarkup(<EmailReferences messages={[{ id: "<untrusted>", thread_id: "thread-1" }]} />);
    expect(html).toContain("Message content was not retrieved");
    expect(html).toContain("&lt;untrusted&gt;");
    expect(html).not.toContain("<untrusted>");
  });

  it("does not claim an empty inbox when no references are present", () => {
    const html = renderToStaticMarkup(<EmailReferences messages={[]} />);
    expect(html).toContain("No message references were returned");
    expect(html).not.toContain("inbox is empty");
  });

  it("does not present simulated references as a live provider read", () => {
    const html = renderToStaticMarkup(<EmailReferences messages={[{ id: "sim-1" }]} sourceObservations={[{ real: false }]} />);
    expect(html).toContain("simulated");
    expect(html).not.toContain("provider read reported");
  });
});
