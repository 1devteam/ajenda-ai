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
      // Core dashboard panels must not fail if credentials:read is missing.
      // Connections are optional checklist signal only.
      const [missionsResult, reviewResult, credentialsResult] = await Promise.allSettled([
        listMissions(session!, { limit: 50 }),
        listReviewQueue(session!, { status: "pending", limit: 50 }),
        listProviderCredentials(session!),
      ]);

      if (cancelled) {
        return;
      }

      const coreErrors: string[] = [];

      if (missionsResult.status === "fulfilled") {
        setMissions(missionsResult.value.missions);
      } else {
        setMissions([]);
        coreErrors.push(failureText(missionsResult.reason));
      }

      if (reviewResult.status === "fulfilled") {
        setApprovalItems(reviewResult.value.items);
        setPendingApprovals(reviewResult.value.total);
      } else {
        setApprovalItems([]);
        setPendingApprovals(0);
        coreErrors.push(failureText(reviewResult.reason));
      }

      if (credentialsResult.status === "fulfilled") {
        const activeCreds = credentialsResult.value.credentials.filter(
          (credential) => credential.enabled && !credential.revoked,
        );
        setHasConnections(activeCreds.length > 0);
      } else {
        // No connections permission → treat as incomplete checklist step, not page error.
        setHasConnections(false);
      }

      if (coreErrors.length > 0) {
        setError(coreErrors[0] ?? "Dashboard data failed to load.");
        setLiveMessage("Dashboard data failed to load.");
      } else {
        setError(null);
        const missionCount =
          missionsResult.status === "fulfilled" ? missionsResult.value.missions.length : 0;
        const approvalCount =
          reviewResult.status === "fulfilled" ? reviewResult.value.total : 0;
        setLiveMessage(
          `Dashboard updated. ${missionCount} missions, ${approvalCount} approvals waiting.`,
        );
      }

      setLoading(false);
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
