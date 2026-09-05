# AegisForge

DevSecOps Vulnerability Intelligence Engine for authorized web applications and REST APIs.

AegisForge will preserve OWASP ZAP evidence, explain findings using advisory Gemini analysis, and enforce deterministic CI/CD policies. It is currently an architecture baseline: no application, scanner, deployment or runtime configuration has been implemented.

## Documentation

- [Working agreement](AGENTS.md)
- [Build plan and dependencies](docs/BUILD_PLAN.md)
- [Phase status and verification](docs/PHASE_STATUS.md)
- [Architecture decisions](docs/DECISIONS.md)
- [System context](docs/architecture/CONTEXT.md)
- [Containers and scan sequence](docs/architecture/CONTAINERS.md)
- [Data model and retention](docs/architecture/DATA_MODEL.md)
- [Scan state machine](docs/architecture/SCAN_STATE_MACHINE.md)
- [Threat model](docs/security/THREAT_MODEL.md)
- [API contract](docs/API_CONTRACT.md)
- [Test matrix](docs/TEST_MATRIX.md)

## Development status

Phase 0 specifies the execution contract. Phase 1 will establish runnable tooling, configuration and lockfiles; there are no install, run or test commands for an application yet. No Markdown lint configuration existed at discovery. Git is configured on `main`, tracking `origin/main` at `git@github.com:AkshatSinghNayal/AegisForge.git`. The original GitHub README commit is preserved beneath the Phase 0 documentation.

The external synopsis and UI references were reviewed in the task. Their source files are outside this workspace and have not been copied or committed. The documentation captures the relevant requirements without reproducing proprietary UI assets.
