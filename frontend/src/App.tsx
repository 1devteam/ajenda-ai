import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useAuthStore } from './services/store';

import LoginPage from './components/layout/LoginPage';
import OverviewPage from './components/overview/OverviewPage';
import AgentsPage from './components/agents/AgentsPage';
import MissionsPage from './components/missions/MissionsPage';
import MissionDetailPage from './components/missions/MissionDetailPage';
import GovernancePage from './components/governance/GovernancePage';
import EconomyPage from './components/economy/EconomyPage';
import ObservabilityPage from './components/observability/ObservabilityPage';
import IntelligencePage from './components/intelligence/IntelligencePage';
import SettingsPage from './components/settings/SettingsPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 10_000,
    },
  },
});

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuthStore();
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<Navigate to="/overview" replace />} />

          <Route path="/overview" element={<ProtectedRoute><OverviewPage /></ProtectedRoute>} />
          <Route path="/agents" element={<ProtectedRoute><AgentsPage /></ProtectedRoute>} />
          <Route path="/agents/:id" element={<ProtectedRoute><AgentsPage /></ProtectedRoute>} />
          <Route path="/missions" element={<ProtectedRoute><MissionsPage /></ProtectedRoute>} />
          <Route path="/missions/new" element={<ProtectedRoute><MissionsPage /></ProtectedRoute>} />
          <Route path="/missions/:id" element={<ProtectedRoute><MissionDetailPage /></ProtectedRoute>} />
          <Route path="/governance" element={<ProtectedRoute><GovernancePage /></ProtectedRoute>} />
          <Route path="/economy" element={<ProtectedRoute><EconomyPage /></ProtectedRoute>} />
          <Route path="/observability" element={<ProtectedRoute><ObservabilityPage /></ProtectedRoute>} />
          <Route path="/intelligence" element={<ProtectedRoute><IntelligencePage /></ProtectedRoute>} />
          <Route path="/settings" element={<ProtectedRoute><SettingsPage /></ProtectedRoute>} />

          <Route path="*" element={<Navigate to="/overview" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
