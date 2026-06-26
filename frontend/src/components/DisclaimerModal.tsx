import type { AutonomyDisclaimer } from "../types";

type DisclaimerModalProps = {
  disclaimer: AutonomyDisclaimer;
  open: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

export default function DisclaimerModal({ disclaimer, open, onCancel, onConfirm }: DisclaimerModalProps) {
  if (!open) {
    return null;
  }

  return (
    <div className="modal-backdrop" role="presentation" onClick={onCancel}>
      <div
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="disclaimer-title"
        onClick={(event) => event.stopPropagation()}
      >
        <p className="eyebrow">Tier {disclaimer.tier} informed autonomy</p>
        <h2 id="disclaimer-title">{disclaimer.disclaimer_id}</h2>
        <p>{disclaimer.text}</p>
        <div className="inline-actions">
          <button type="button" className="ghost-button" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="primary-button" onClick={onConfirm}>
            I understand — continue
          </button>
        </div>
      </div>
    </div>
  );
}