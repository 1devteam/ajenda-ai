import { Link } from "react-router-dom";
import StatusBadge from "./StatusBadge";

type MissionCardProps = {
  missionId: string;
  title: string;
  status: string;
  meta?: string;
};

export default function MissionCard({ missionId, title, status, meta }: MissionCardProps) {
  return (
    <Link className="mission-card" to={`/missions/${missionId}`}>
      <div className="mission-card-header">
        <strong>{title}</strong>
        <StatusBadge status={status} />
      </div>
      {meta ? <span className="muted">{meta}</span> : null}
    </Link>
  );
}