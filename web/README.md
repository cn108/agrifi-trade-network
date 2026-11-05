# AgriFi Angular dashboard

The Angular + Tailwind dashboard is separate from the preserved legacy React app in `../frontend/`.
It provides buyer/farmer registration, browser login, self-service profile editing, and role-aware
farmer, buyer, operations and finance workflows backed by the Django API.

## Run locally

From this directory:

```powershell
npm.cmd start
```

The app is served at `http://localhost:4200`. Django must be available at `http://localhost:8000`.
Set `DJANGO_CORS_ALLOWED_ORIGINS=http://localhost:4200` for local browser development.
The API uses the same validated origins for CSRF trust. Do not use wildcard origins.

The API base URL is configured in `src/environments/environment.ts`. Use HTTPS for deployed
environments and set the API's production cookie/CORS/CSRF environment variables accordingly.

## Browser session security

- The refresh token is delivered only through the API's HttpOnly cookie transport.
- The short-lived access token exists only in Angular service memory; it is not written to
  `localStorage`, `sessionStorage`, SQLite, or logs.
- Cookie login, refresh and logout requests send credentials and the CSRF header.
- API requests send the access token as a Bearer credential. A 401 response attempts one cookie
  refresh and retries the original request once.
- Production must use HTTPS and a Secure refresh cookie. Review `../README.md` for the backend
  cookie, CORS and CSRF configuration contract.

## Commands

```powershell
npm.cmd run build
npm.cmd test
```

Dashboard data and writes use `/api/v1/`; the app does not fabricate business metrics or calculate
authoritative order totals. Finance records and actions are labelled simulated and are not real
payments or payouts. The production build and current unit tests pass; live browser/API integration
has not yet been verified.
