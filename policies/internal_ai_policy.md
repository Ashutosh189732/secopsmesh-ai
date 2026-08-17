# Internal AI Usage Policy

This policy governs how internal services, deployment automation, and
employees may interact with the organization's AI/ML endpoints (including
Azure OpenAI deployments) and how AI-assisted agents may act on production
systems.

## Service Identity Access

Service identities (such as `svc-deploy-bot` and other automation
accounts) that call AI endpoints must operate within pre-approved call
volume baselines established during onboarding. A sustained call volume
significantly above baseline (for example, more than 10x the historical
hourly average) from a single service identity must be treated as a
potential indicator of credential compromise, a runaway automation loop, or
unauthorized use of the identity for purposes outside its original
approval, and investigated before being dismissed as benign.

## Deployment Automation Boundaries

Automated deployment pipelines are permitted to modify infrastructure
configuration, including storage account access settings, only within the
scope explicitly reviewed and approved in the corresponding pull request.
Any deployment that changes a security-relevant setting (public network
access, IAM role bindings, encryption configuration) outside of what was
reviewed constitutes a policy violation regardless of whether the change
was intentional, and must be treated as a security incident pending
investigation, not merely a rollback candidate.

## AI Agent Autonomy Limits

Autonomous investigation and remediation agents (such as this system's
orchestrator and remediation planner) may read evidence from monitoring,
version control, and identity systems without additional approval. They
must not take remediation actions with production impact — closing public
access, revoking credentials, rolling back deployments — without human
approval, except where a pre-approved low-risk remediation playbook
explicitly authorizes automatic action.

## Data Handling by AI Agents

Evidence and incident data passed to LLM-based agents (Root Cause, Risk,
Remediation) must not include raw customer PII beyond what is strictly
necessary to explain the incident, and any output referencing personal data
exposure must flag it explicitly so downstream compliance workflows (GDPR
Article 33, HIPAA Breach Notification) are triggered rather than silently
absorbed into a generic incident summary.
