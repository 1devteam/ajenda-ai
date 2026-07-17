import { useNavigate } from "react-router-dom";
import type { AttentionBanner as BannerModel } from "../../dashboard/dashboardModel";
import Card from "../primitives/Card";
import Button from "../primitives/Button";

type AttentionBannerProps = {
  banner: BannerModel;
};

export default function AttentionBanner({ banner }: AttentionBannerProps) {
  const navigate = useNavigate();
  const isBlocking = banner.severity === "blocking";
  const border = isBlocking
    ? "border-crimson/40 bg-crimson/5"
    : banner.id === "quota"
      ? "border-semantic-warning/30 bg-semantic-warning/5"
      : "border-semantic-info/30 bg-semantic-info/5";
  const accent = isBlocking
    ? "text-crimson-bright"
    : banner.id === "quota"
      ? "text-semantic-warning"
      : "text-semantic-info";

  return (
    <Card className={`mb-4 ${border}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-zinc-200">
          <strong className={accent}>{banner.message}</strong>
        </p>
        <Button variant={isBlocking ? "danger" : "subtle"} onClick={() => navigate(banner.to)}>
          {banner.cta}
        </Button>
      </div>
    </Card>
  );
}
