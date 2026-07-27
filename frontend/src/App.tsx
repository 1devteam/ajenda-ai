import { BrowserRouter, Route, Routes } from "react-router-dom";
import SessionWatchdog from "./auth/SessionWatchdog";
import AppLayout from "./components/AppLayout";
import PublicSiteLayout from "./components/marketing/PublicSiteLayout";
import ProtectedRoute from "./components/ProtectedRoute";
import ApprovalsPage from "./pages/ApprovalsPage";
import BillingPage from "./pages/BillingPage";
import DashboardPage from "./pages/DashboardPage";
import DevConsolePage from "./pages/DevConsolePage";
import PromotePage from "./pages/PromotePage";
import AuthCallbackPage from "./pages/AuthCallbackPage";
import SignInPage from "./pages/SignInPage";
import SignupPage from "./pages/SignupPage";
import MissionsPage from "./pages/MissionsPage";
import MissionDispatchPage from "./pages/MissionDispatchPage";
import TasksPage from "./pages/TasksPage";
import RecordsPage from "./pages/RecordsPage";
import CredentialsPage from "./pages/CredentialsPage";
import BusinessProfilePage from "./pages/BusinessProfilePage";
import StandaloneWizardPage from "./pages/StandaloneWizardPage";
import SettingsPage from "./pages/SettingsPage";
import VerifyEmailPage from "./pages/VerifyEmailPage";
import HomePage from "./pages/marketing/HomePage";
import ProductPage from "./pages/marketing/ProductPage";
import PricingPage from "./pages/marketing/PricingPage";
import SecurityPage from "./pages/marketing/SecurityPage";
import PrivacyPage from "./pages/marketing/PrivacyPage";
import TermsPage from "./pages/marketing/TermsPage";
import NotFoundPage from "./pages/marketing/NotFoundPage";
import { PUBLIC_SITE_ROUTES } from "./config/marketingRoutes";

export default function App() {
  return (
    <BrowserRouter>
      <SessionWatchdog />
      <Routes>
        <Route element={<PublicSiteLayout />}>
          <Route index element={<HomePage />} />
          <Route path={PUBLIC_SITE_ROUTES.product.path} element={<ProductPage />} />
          <Route path={PUBLIC_SITE_ROUTES.pricing.path} element={<PricingPage />} />
          <Route path={PUBLIC_SITE_ROUTES.security.path} element={<SecurityPage />} />
          <Route path={PUBLIC_SITE_ROUTES.privacy.path} element={<PrivacyPage />} />
          <Route path={PUBLIC_SITE_ROUTES.terms.path} element={<TermsPage />} />
        </Route>
        <Route element={<AppLayout />}>
          <Route path="/signin" element={<SignInPage />} />
          <Route path="/auth/callback" element={<AuthCallbackPage />} />
          <Route path="/signup" element={<SignupPage />} />
          <Route path="/verify-email" element={<VerifyEmailPage />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/promote" element={<PromotePage />} />
          </Route>
          <Route element={<ProtectedRoute requireOperational />}>
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/setup" element={<StandaloneWizardPage />} />
            <Route path="/business" element={<BusinessProfilePage />} />
            <Route path="/missions" element={<MissionsPage />} />
            <Route path="/launch" element={<MissionsPage />} />
            <Route path="/missions/:missionId" element={<MissionDispatchPage />} />
            <Route path="/billing" element={<BillingPage />} />
            <Route path="/billing/success" element={<BillingPage />} />
            <Route path="/billing/cancel" element={<BillingPage />} />
            <Route path="/tasks" element={<TasksPage />} />
            <Route path="/active-work" element={<TasksPage />} />
            <Route path="/approvals" element={<ApprovalsPage />} />
            <Route path="/records" element={<RecordsPage />} />
            <Route path="/results" element={<RecordsPage />} />
            <Route path="/credentials" element={<CredentialsPage />} />
            <Route path="/connections" element={<CredentialsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/credentials/gmail/callback" element={<CredentialsPage />} />
            <Route path="/credentials/linkedin/callback" element={<CredentialsPage />} />
            <Route path="/credentials/salesforce/callback" element={<CredentialsPage />} />
            <Route path="/credentials/google-calendar/callback" element={<CredentialsPage />} />
            <Route path="/credentials/google-contacts/callback" element={<CredentialsPage />} />
            <Route path="/credentials/github/callback" element={<CredentialsPage />} />
          </Route>
          <Route path="/dev" element={<DevConsolePage />} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  );
}
