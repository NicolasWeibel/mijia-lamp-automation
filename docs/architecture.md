# Architecture v3.1

[English](architecture.md) | [Español](es/architecture.md)


MijiaLamp shares one core (`policy`, `StateStore`, `LampController`, `LampTransport`, `ServiceCore`) and provides two hosts.

## Shared invariants

1. A new intent invalidates old work (`intent_revision`).
2. Critical OFF takes priority (`critical_off_revision`).
3. Runtime state is not confused with physical state.
4. Unknown display/session/presence does not automatically mean ON.
5. Discovery validates the model + DID before adopting an IP.

## Portable host

`portable.py` creates `LampController + ServiceCore` in the user's process and opens `MijiaLamp-Portable-v3` for the CLI/tray/events. It uses DPAPI `CurrentUser`.

There is no service or elevated code. Windows shutdown is best effort because the process belongs to the interactive session.

## Service host

`service.py` hosts the same core under `LocalService`. `agent.py` only observes Windows and uses IPC; it does not import `miio` or `secrets_store`.

SCM delivers Preshutdown/Shutdown/Power directly to the service, so OFF does not depend on starting a task during system shutdown.

## Hardened installation

The Service release may include an already prepared private runtime. If it does not, the user first runs `prepare-service-runtime.ps1` without Administrator privileges. `install.ps1` verifies SHA-256, prepares staging, stops the previous version only at the end, and swaps it in. If installation fails, it restores previous files without running their runtime with elevated privileges; automation is not restarted until a verified installation is repeated.

## Concurrent IPC

Each connection has its own worker, with a bounded maximum. Critical Agent events use one-way messages so `WM_POWERBROADCAST` does not wait for a slow `doctor` or sync.
