# Security Policy

This repository contains a sample Teradata retail-banking data warehouse
(DDL, views, stored procedures, macros, BTEQ scripts and synthetic seed data)
used as the source for a Teradata-to-Snowflake migration lab.

## Supported Versions

There are no versioned releases. Only the latest commit on the `main` branch
is supported and receives security fixes.

| Version         | Supported |
| --------------- | --------- |
| `main` (latest) | Yes       |
| Older commits   | No        |

## Reporting a Vulnerability

**Do not open a public issue or pull request for security problems.**

Report vulnerabilities privately through GitHub Private Vulnerability Reporting:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability** (under *Advisories*).
3. Describe the issue, the affected files (e.g. a SQL script, BTEQ script or
   seed CSV), steps to reproduce, and the potential impact.

The maintainers listed in `.github/CODEOWNERS` will acknowledge the report
within 5 business days, keep you updated on progress, and coordinate a fix
and disclosure through a GitHub Security Advisory.

## Scope

Relevant reports include, for example:

- Hard-coded credentials, logon strings or connection details in BTEQ
  (`.logon`) scripts, SQL or documentation.
- Real (non-synthetic) personal or financial data in `data/seed/` — all
  customer data in this repository must be fictitious.
- SQL that would grant excessive privileges or expose sensitive columns
  when deployed (e.g. in views or stored procedures).
- Vulnerabilities in the CI workflow or its dependencies.
