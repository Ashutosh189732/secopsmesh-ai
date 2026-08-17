# SOC 2 — Service Organization Control 2

SOC 2 defines criteria for managing customer data based on five Trust
Services Criteria: security, availability, processing integrity,
confidentiality, and privacy. Most cloud-hosted SaaS vendors are audited
against the Security criterion at minimum, and increasingly against
Confidentiality as well.

## CC6 — Logical and Physical Access Controls

The CC6 series of common criteria governs how an organization restricts
logical and physical access to protect its systems from unauthorized access.
Key sub-criteria relevant to cloud infrastructure incidents:

- **CC6.1** — The entity implements logical access security software,
  infrastructure, and architectures over protected information assets to
  protect them from security events. This includes least-privilege IAM
  policies, and default-deny network/storage access configurations.
- **CC6.3** — The entity authorizes, modifies, or removes access to data,
  software, functions, and other protected information assets based on
  roles, responsibilities, or the system design and changes, giving
  consideration to the concept of least privilege.
- **CC6.6** — The entity implements logical access security measures to
  protect against threats from sources outside its system boundaries,
  including restricting inbound and outbound connections and access from
  untrusted networks.

A deployment or infrastructure change that flips a storage resource's access
control from private to public directly violates CC6.1 and CC6.3 — access
was granted (to the entire internet) without authorization tied to a
legitimate role or business need. An unauthorized or anomalous API call
volume against a sensitive service (for example, an unexpected surge of
calls to an internal AI/ML endpoint from a service identity) is evidence
relevant to CC6.6 and should be captured in the audit trail supporting the
next SOC 2 examination period. Auditors will expect incident tickets for
CC6-relevant events to include root cause, remediation, and time-to-detect.
