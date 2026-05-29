# xbot-next

`xbot-next` is a new modular backend framework for xbot.

This directory is intentionally independent from the existing project. The old project is used only as a capability reference, not as a codebase to migrate directly.

## Current Phase

Backend first.

Frontend is out of scope until the backend framework can run independently with:

- configuration loading
- runtime lifecycle
- management API
- adapter abstraction
- standard message model
- plugin loading
- skill loading
- agent runtime
- tool calling
- message dispatch
- simple example plugin
- PostgreSQL persistence

## Design Document

See:

- [Backend Framework Design](docs/backend-framework-design.md)

## Planned MVP

1. Project skeleton
2. FastAPI app
3. Config and logging
4. `XBotEngine`
5. Standard `Message` and `Reply`
6. `BaseAdapter` and `WebAdapter`
7. Plugin base class and plugin manager
8. Skill manager
9. Agent runtime and tool registry
10. Echo example plugin
11. PostgreSQL persistence
12. Basic management API
