import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import Button from "../primitives/Button";

type SetupReminderProps = {
  onMaybeLater: () => void;
  onSuppress: () => Promise<void>;
};

export default function SetupReminder({ onMaybeLater, onSuppress }: SetupReminderProps) {
  const navigate = useNavigate();
  const dialogRef = useRef<HTMLDivElement>(null);
  const checkboxRef = useRef<HTMLInputElement>(null);
  const [suppress, setSuppress] = useState(false);
  const previousFocus = useRef<HTMLElement | null>(null);
  useEffect(() => {
    previousFocus.current = document.activeElement as HTMLElement | null;
    checkboxRef.current?.focus();
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onMaybeLater();
      if (event.key === "Tab" && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll<HTMLElement>("button, input, [href], [tabindex]:not([tabindex='-1'])");
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      previousFocus.current?.focus();
    };
  }, [onMaybeLater]);

  return (
    <div className="setup-reminder-backdrop" role="presentation">
      <div
        ref={dialogRef}
        className="setup-reminder-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="setup-reminder-title"
        aria-describedby="setup-reminder-description"
      >
        <p className="cc-section-kicker">Workspace setup</p>
        <h2 id="setup-reminder-title">Finish setting up Ajenda</h2>
        <p id="setup-reminder-description">Add your company details and connect the tools you want Ajenda to use.</p>
        <ul className="setup-reminder-progress">
          <li>✓ Company information</li>
          <li>○ Operating preferences</li>
          <li>○ Connections</li>
        </ul>
        <label className="checkbox-row">
          <input ref={checkboxRef} type="checkbox" checked={suppress} onChange={(event) => setSuppress(event.target.checked)} />
          Don&apos;t show this setup reminder again
        </label>
        <div className="setup-reminder-actions">
          <Button variant="ghost" onClick={() => { if (suppress) void onSuppress(); onMaybeLater(); }}>Maybe later</Button>
          <Button variant="primary" onClick={() => navigate("/setup")}>Start setup</Button>
        </div>
      </div>
    </div>
  );
}
