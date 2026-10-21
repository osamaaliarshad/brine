# Sign-in: setting up an OIDC provider

brine signs people in with OpenID Connect, so your team uses the accounts they already have.
Each brine deployment registers **its own** client with its own provider: nothing is shared
between installs, and no client ID or secret ships with brine.

The [demo](../README.md#demo-salt-fleet) runs with sign-in off (`auth.provider: none`), so you
don't need any of this to try brine.

## What every provider needs

1. **Register a "web application" client** (sometimes called confidential client) that uses the
   authorization code flow.
2. **Allow one redirect URI:** `<public_url>/api/auth/callback`, for example
   `https://brine.example.com/api/auth/callback`. It must match exactly: scheme, host, port and
   path.
3. **Put the client in brine's config.** Keep the ID and secret out of the file with `${VAR}`
   placeholders and set them in the environment:

   ```yaml
   public_url: https://brine.example.com   # how browsers reach brine

   auth:
     provider: oidc
     issuer: https://accounts.google.com  # see each provider below
     client_id: ${OIDC_CLIENT_ID}
     client_secret: ${OIDC_CLIENT_SECRET}
     allowed_domains: [example.com]       # optional: refuse every other domain outright

   roles:                                 # email patterns, highest matching role wins
     viewer:   ["*@example.com"]
     operator: ["alice@example.com"]
     admin:    ["bob@example.com"]
   ```

brine reads `<issuer>/.well-known/openid-configuration`, asks for the `openid email profile`
scopes, and identifies people by the `email` claim. It refuses a sign-in unless the provider
says the email is verified (`email_verified: true`), when the domain isn't in `allowed_domains`,
or when no role pattern matches. Roles are checked again on every request, so removing someone from `roles` takes effect
on their next click, not when their session ends.

If `auth` is half filled in (say, an issuer but no secret), brine refuses to start and says what's
missing, rather than quietly running with sign-in off.

### Trying it locally

Register `http://localhost:5173/api/auth/callback` (the Vite dev server, which forwards `/api`
to the backend) and, if you also open the backend directly, `http://localhost:8000/api/auth/callback`.
Put the ID and secret in a git-ignored `.env` at the repo root (see `.env.example`) and start the
backend with it:

```bash
cd backend
BRINE_CONFIG=../config.yaml uv run --env-file ../.env uvicorn app.main:create_app --factory --reload
```

### Behind a reverse proxy

Set `public_url`. Without it brine builds the redirect URI from each request, which only works
when the proxy forwards the original `Host` header and scheme. Session cookies are marked
`Secure` whenever `public_url` starts with `https://`.

## Google

Works for personal Google accounts and Google Workspace.

1. In the [Google Cloud console](https://console.cloud.google.com/), pick or create a project.
2. **Google Auth Platform › Branding:** give the app a name and support email.
3. **Audience:** *Internal* (Workspace only) limits sign-in to your organisation. *External*
   starts in testing mode, where only the test users you list can sign in; that's fine for a
   small team.
4. **Clients › Create client:** type *Web application*, add the redirect URI(s) above.
5. Copy the client ID and secret into your environment.

```yaml
auth:
  issuer: https://accounts.google.com
  allowed_domains: [example.com]   # your Workspace domain; leave out for personal accounts
```

## Okta

1. **Applications › Create App Integration:** *OIDC - OpenID Connect*, then *Web Application*.
2. Grant type *Authorization Code*; add the redirect URI as a sign-in redirect URI.
3. Assign the people or groups who should reach brine (roles in brine's config still apply).

```yaml
auth:
  issuer: https://example.okta.com   # or https://example.okta.com/oauth2/default
```

## Microsoft Entra ID (Azure AD)

1. **App registrations › New registration.** Supported account types: *this organizational
   directory only* (single tenant). Redirect URI: platform *Web*, the URI above.
2. **Certificates & secrets › New client secret.** Copy the value (shown once).
3. **Token configuration › Add optional claim › ID token › `email`.**

```yaml
auth:
  issuer: https://login.microsoftonline.com/<tenant-id>/v2.0
  allowed_domains: [example.com]
  require_verified_email: false    # Entra never sends email_verified
```

Use the single-tenant issuer above, never `common` or `organizations`. Entra doesn't send
`email_verified`, so brine can't require it, and in multi-tenant setups the `email` claim can be
set by another tenant's admin. In your own tenant only your admins control it, which is why the
single-tenant issuer and `allowed_domains` matter here.

## Keycloak

1. In your realm, **Clients › Create client:** type *OpenID Connect*, then turn on *Client
   authentication* and *Standard flow*.
2. Add the redirect URI under *Valid redirect URIs*.
3. Copy the secret from the client's *Credentials* tab.

```yaml
auth:
  issuer: https://keycloak.example.com/realms/<realm>
```

Keycloak sends `email_verified`; users whose email isn't verified in Keycloak are refused.

## GitHub, GitLab and others without OIDC

GitHub's sign-in is plain OAuth 2.0, not OpenID Connect, so brine can't use it directly. Put an
OIDC broker in front: [Dex](https://dexidp.io/) and Keycloak can both sign people in with GitHub
and hand brine a standard OIDC identity. GitLab, authentik, Authelia, Zitadel and other OIDC
providers work with the general steps above.

## Sign-in off

```yaml
auth:
  provider: none
  anonymous_role: viewer   # what everyone gets; brine shows a banner saying so
```

For the demo and for single-user setups on a trusted network only: anyone who can reach brine
gets `anonymous_role`. Nothing is asked of anyone, and the audit log records them as `local`.
