# Private Ajenda development studio

Use `https://dev.ajenda.ai` to inspect and reproduce UI behavior in a running Ajenda Compose development instance. Both the operator and the shared browser must use this instance and the same development tenant to see the same records and mission state.

## Configure access and routing

1. On the host running Ajenda, confirm that `curl -fsS http://127.0.0.1:8080/readiness` succeeds. Use a development tenant and test data for shared-browser work.
2. In the Cloudflare Zero Trust dashboard, create a **self-hosted Access application** covering all paths on `dev.ajenda.ai` before adding a published route. Allow only the intended operator identities through your identity provider. Route-wide coverage includes `/v1/*`.
3. Install and enroll `cloudflared` on the host that can reach Ajenda's published loopback port. Use Cloudflare's generated installation command for that host and keep the tunnel token in the host's service configuration. A Cloudflare–GitHub connection does not enroll this connector.
4. Publish `dev.ajenda.ai` through the enrolled tunnel with service URL `http://127.0.0.1:8080`. In the route's origin settings, enable **Protect with Access** using the Access application from step 2 so `cloudflared` validates the Access token before forwarding requests.

The existing [Compose frontend](../../docker-compose.yml) publishes port `8080` on loopback. Its [nginx configuration](../../deploy/nginx/frontend.compose.conf) serves the UI and proxies `/v1/` and `/readiness` to the internal API. Use `https://dev.ajenda.ai` as the browser entry point for both UI pages and API requests. Keep any frontend or session API base override on the same origin. The tunnel needs only the frontend origin.

## Verify browser access

1. In a fresh browser profile without an Access session, open `https://dev.ajenda.ai/results` and `https://dev.ajenda.ai/v1/system/readiness`. Both should be intercepted by Cloudflare Access. If either returns Ajenda content, remove the published route and fix the Access application before restoring it.
2. From the shared browser, sign in to Cloudflare Access and then sign in to Ajenda with the application account for the development tenant. Open **Outcomes**, switch between **Companies** and **Contacts**, and reload the page. Confirm the UI and its `/v1/` requests succeed on `https://dev.ajenda.ai`.
3. To reproduce the mission issue, open the mission detail page in that tenant, perform **Start execution** on a test mission, and record the resulting status or error. Browser access is verified once both sign-ins and the read-only CRM pages work. Mission execution has its own result.

To take the studio offline, remove the published application route from the tunnel or stop its connector if the connector is dedicated to this studio.

Cloudflare references: [Access for a self-hosted application](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/) and [Tunnel setup and published routes](https://developers.cloudflare.com/tunnel/get-started/).
