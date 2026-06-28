import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { loadSession } from "./auth/session";
import AppLayout from "./components/AppLayout";
import ProtectedRoute from "./components/ProtectedRoute";
import BillingPage from "./pages/BillingPage";
import DashboardPage from "./pages/DashboardPage";
import DevConsolePage from "./pages/DevConsolePage";
import PromotePage from "./pages/PromotePage";
import AuthCallbackPage from "./pages/AuthCallbackPage";
import SignInPage from "./pages/SignInPage";
import SignupPage from "./pages/SignupPage";
import MissionsPage from "./pages/MissionsPage";
import TasksPage from "./pages/TasksPage";
import CredentialsPage from "./pages/CredentialsPage";
import VerifyEmailPage from "./pages/VerifyEmailPage";

function HomeRedirect() {
  const session = loadSession();
  if (!session) {
    return <Navigate to="/signin" replace />;
  }
  if (session.phase === "bootstrap") {
    return <Navigate to="/promote" replace />;
  }
  return <Navigate to="/dashboard" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<HomeRedirect />} />
          <Route path="/signin" element={<SignInPage />} />
          <Route path="/auth/callback" element={<AuthCallbackPage />} />
          <Route path="/signup" element={<SignupPage />} />
          <Route path="/verify-email" element={<VerifyEmailPage />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/promote" element={<PromotePage />} />
          </Route>
          <Route element={<ProtectedRoute requireOperational />}>
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/missions" element={<MissionsPage />} />
            <Route path="/billing" element={<BillingPage />} />
            <Route path="/billing/success" element={<BillingPage />} />
            <Route path="/billing/cancel" element={<BillingPage />} />
            <Route path="/tasks" element={<TasksPage />} />
            <Route path="/credentials" element={<CredentialsPage />} />
            <Route path="/credentials/gmail/callback" element={<CredentialsPage />} />
            <Route path="/credentials/linkedin/callback" element={<CredentialsPage />} />
            <Route path="/credentials/salesforce/callback" element={<CredentialsPage />} />
            <Route path="/credentials/google-calendar/callback" element={<CredentialsPage />} />
            <Route path="/credentials/github/callback" element={<CredentialsPage />} />
          </Route>
          <Route path="/dev" element={<DevConsolePage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}