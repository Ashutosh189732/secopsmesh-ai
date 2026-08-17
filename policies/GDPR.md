# GDPR — General Data Protection Regulation

The General Data Protection Regulation (EU) 2016/679 governs the processing
of personal data belonging to individuals in the European Union. It applies
to any organization that stores or processes such data, regardless of where
the organization itself is located.

## Article 32 — Security of Processing

Article 32 requires controllers and processors to implement appropriate
technical and organizational measures to ensure a level of security
appropriate to the risk, including the pseudonymisation and encryption of
personal data, and the ability to ensure ongoing confidentiality, integrity,
availability, and resilience of processing systems. In practice this means
cloud storage resources holding personal data (customer records, export
files, analytics datasets containing identifiable information) must never be
configured for public or anonymous access. A storage bucket or container
whose access control list is changed to allow public read access — whether
through a misconfigured deployment, a manual console change, or an
infrastructure-as-code regression — constitutes a direct Article 32 breach
of confidentiality if it holds personal data, independent of whether the
data was actually accessed by an unauthorized party.

## Article 33 — Notification of a Personal Data Breach

Where a personal data breach is likely to result in a risk to the rights and
freedoms of individuals, the controller must notify the relevant supervisory
authority within 72 hours of becoming aware of it. This makes rapid,
evidence-backed root cause determination operationally critical, not just a
compliance nicety: incident responders need to establish quickly whether
personal data was exposed, for how long, and to whom, in order to meet the
notification deadline.
