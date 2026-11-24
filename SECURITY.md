# Security

A dope CLI is a local tool for a trusted user on their own Mac. It is not a
multi-tenant service and not a sandbox for untrusted code.

`bin/dope` runs every command, the worker and the engines under a macOS
network-deny sandbox profile. Workers also keep process limits and immutable
revision checks. These controls do not protect against every native parser or
kernel vulnerability, so stay within the documented input and format bounds.

Do not expose the MCP server, the project store or engine processes to other users
or to the network. Keep credentials and client files out of the repository.

Report vulnerabilities privately to the maintainer, not in a public issue. This
file does not promise a response time or production support.
