# 1. Getting Started

This guide will walk you through the initial setup and basic concepts of Omnipath v2.

## Creating a Tenant

Your tenant is your isolated workspace within Omnipath. All your agents, missions, and data are scoped to your tenant.

To create a tenant, you will need to make a `POST` request to the `/api/v1/tenants` endpoint. You will receive a `tenant_id` and an API key in the response. **Store this API key securely**, as it is used to authenticate all subsequent requests.

## The User Interface

While Omnipath is primarily an API-driven platform, the monitoring stack includes Grafana dashboards that provide a real-time view into your operations. You can access these dashboards at the `/grafana` endpoint of your deployment. Key dashboards include:

- **Governance:** High-level overview of risk, compliance, and agent activity.
- **API Performance:** Detailed metrics on API request rates, latency, and errors.
- **System Health:** Infrastructure-level metrics for CPU, memory, and database performance.
- **Logs:** A searchable log explorer powered by Loki.