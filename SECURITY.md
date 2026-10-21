# Security

## Reporting a problem

Please don't open a public issue for a security problem. Report it privately through GitHub:
the repository's **Security** tab, then **Report a vulnerability**. You'll get an answer within a
week, and credit in the release notes if you'd like it.

## What brine protects

- **Salt credentials stay on the server.** People sign in with your identity provider; only
  brine's backend talks to salt-api, with one service account whose ACL you choose
  ([docs/permissions-and-salt-acl.md](docs/permissions-and-salt-acl.md)). Secrets in the config
  never reach a browser.
- **Roles are checked on every request,** against the config: removing someone takes effect on
  their next click. Commands need a role allowed to run them, and runs, key changes, sign-ins
  and pillar views go in the audit log.
- **Writes need a header other sites can't send** (CSRF), requests that another site sends a
  browser to are refused, and pages can't be framed by other sites.
- **Pillar values are for admins.** brine's own Pillar tab masks every value; output of pillar
  functions someone runs is shown to admins only.

## Things to know

- **Job output is visible to everyone signed in** (pillar output excepted). If people run
  commands whose output contains secrets, give viewer access only to people who may see them.
- **So are package lists, and check commands and their output.** Keep secrets out of check
  commands, and don't write checks that print them.
- **Checks let brine's Salt account run any command.** Salt pins each check's command but not the
  call's other options (`shell`, `env`, `runas`, `cwd`). So anyone holding that account's
  password, or controlling brine's server, can run commands on your minions
  ([details](docs/permissions-and-salt-acl.md#4-optional-checks)). Leave checks out if the
  account should stay read-only.
- **Checks also widen the Run page.** With a check's rule in place, anyone brine lets run
  `cmd.run_all` can use it to run any command. By default that's every admin (`commands.admin`
  is `["*"]`), plus operators allowed `cmd.*`. Give both lists explicit entries without
  `cmd.run_all` if that matters.
- **Who ran a job** comes from Salt job metadata that brine sets. Someone with shell access to the
  master could set the same metadata on a job of their own; the audit log is the record to trust.
- **Signing out** clears the session in that browser. A copied session cookie keeps working until
  it expires (`auth.session_hours`, 12 by default). To sign everyone out at once, set a new
  `auth.session_secret`.
- **Sign-in off** (`auth.provider: none`) makes everyone who can reach brine an admin, or
  whatever `auth.anonymous_role` says. Use it for the demo or on your own machine only.
- **Run it behind HTTPS** (a reverse proxy) for anything beyond your own machine, and set
  `public_url`, so session cookies are marked Secure and sign-in redirects are right.
