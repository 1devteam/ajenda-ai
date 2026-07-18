import { useCallback, useEffect, useState } from "react";
import { listMissions, listProviderCredentials, listReviewQueue } from "../api/client";
import type { CustomerSession, MissionListItem, ReviewQueueItem } from "../types";
import { failureText } from "../utils/errors";

export type DashboardData = {
  missions: MissionListItem[];
  approvalItems: ReviewQueueItem[];
  pendingApprovals: number;
  hasConnections: boolean;
  loading: boolean;
  error: string | null;
  liveMessage: string;
  reload: () => void;
};

export function useDashboardData(session: CustomerSession | null): DashboardData {
  const [missions, setMissions] = useState<MissionListItem[]>([]);
  const [approvalItems, setApprovalItems] = useState<ReviewQueueItem[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState(0);
  const [hasConnections, setHasConnections] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [liveMessage, setLiveMessage] = useState("");
  const [reloadToken, setReloadToken] = useState(0);

  const reload = useCallback(() => {
    setReloadToken((value) => value + 1);
  }, []);

  useEffect(() => {
    if (!session) {
      setMissions([]);
      setApprovalItems([]);
      setPendingApprovals(0);
      setHasConnections(false);
      setLoading(false);
      setError(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    async function load() {
      try {
        const [missionResponse, reviewResponse, credentialsResponse] = await Promise.all([
          listMissions(session!, { limit: 50 }),
          listReviewQueue(session!, { status: "pending", limit: 50 }),
          listProviderCredentials(session!),
        ]);
        if (cancelled) {
          return;
        }
        const activeCreds = credentialsResponse.credentials.filter(
          (credential) => credential.enabled && !credential.revoked,
        );
        setMissions(missionResponse.missions);
        setApprovalItems(reviewResponse.items);
        setPendingApprovals(reviewResponse.total);
        setHasConnections(activeCreds.length > 0);
        setLiveMessage(
          `Dashboard updated. ${missionResponse.missions.length} missions, ${reviewResponse.total} approvals waiting.`,
        );
      } catch (err) {
        if (!cancelled) {
          setError(failureText(err));
          setLiveMessage("Dashboard data failed to load.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [session, reloadToken]);

  return {
    missions,
    approvalItems,
    pendingApprovals,
    hasConnections,
    loading,
    error,
    liveMessage,
    reload,
  };
}
