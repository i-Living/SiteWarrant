# Vendored third-party code

## axe-core

- File: `axe.min.js`
- Version: 4.14.0
- Source: `https://unpkg.com/axe-core@4.14.0/axe.min.js`
- SHA-256: `20c09fe157a8a34a30e241aaa1fcdade657734f08ab379ecfbeb7d45cc46e878`
- License: Mozilla Public License 2.0, full text in `axe.LICENSE`
- Copyright: Deque Systems, Inc.

Why vendored instead of fetched at runtime: an audit must produce the same result on a machine
without network access to a CDN, and the version that produced a report has to be part of
`agent_version`. Bumping the version means updating `AXE_VERSION` in `app/tools/axe.py`, this
file, and the hash — that changes `agent_version`, which is the point.
