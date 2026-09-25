# Security

Interlock sends a compiled, redacted state to a hosted sensor. The compiler strips emails, phone numbers,
card-shaped numbers and known credential patterns *after* computing features on them; the audit log stores
hashes and probabilities, never content, except an override justification a person typed.

Passing the gate is not a guarantee of safety. It is a judgment layer that catches regret-shaped mistakes.

To report a vulnerability, open a GitHub security advisory on the repository rather than a public issue.
