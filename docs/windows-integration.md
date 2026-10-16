# Windows 10/11 integration

[English](windows-integration.md) | [Español](es/windows-integration.md)


## Interactive events

`agent.py` creates a hidden Win32 window and registers for:

- `GUID_SESSION_DISPLAY_STATUS`;
- `GUID_SESSION_USER_PRESENCE` when available;
- `WTSRegisterSessionNotification` for Lock/Unlock/Logon/Logoff/console/RDP;
- `WM_POWERBROADCAST` for Suspend/Resume.

Both modes share this Agent.

## Portable

`portable.py` hosts the core in the same user process. The Agent sends events to the `MijiaLamp-Portable-v3` Pipe. The process exists only while the session is active.

It can be added to the user's Startup folder with `enable-portable-autostart.ps1`; Administrator privileges are not required.

Deliberate limitation: shutdown/logoff is **best effort**. Windows may end the session before a LAN command completes.

## Service

`MijiaLampService` runs as `LocalService` and also receives SCM controls:

- `SERVICE_CONTROL_PRESHUTDOWN`;
- `SERVICE_CONTROL_SHUTDOWN`;
- `SERVICE_CONTROL_POWEREVENT`.

Therefore, the shutdown/suspend OFF does not depend on starting new processes at the end of shutdown.

The service does not assume that starting Windows means the user is present. A service restart invalidates Display/WTS/Presence until Agent publishes a real snapshot again.

### Light before sign-in (optional)

With `service_prelogin_display: true`, Service registers for `GUID_CONSOLE_DISPLAY_STATE` and receives the console's current display state as well as later changes. If the sign-in screen is on and the schedule says it is nighttime, automation can turn on the lamp before signing in to Windows. When the display turns off, policy requests OFF. The callback only queues the event; LAN control runs outside the Windows callback. Portable cannot do this because it starts inside the user's session.

To keep the lamp on while the screen is locked, set `off_on_session_lock: false` and `respect_user_presence: false`. Automation must be enabled, the local network must be available, and the Service token must be imported with LocalMachine scope. Manual-off and pause overrides still take priority. If Windows does not provide a valid display signal, keep `unknown_display_policy: "off"` to avoid an unrequested turn-on.

This option needs a real Service test after restarting Windows without signing in: verify ON while the screen is visible and OFF when it turns off. Registration was tested in an interactive Windows session, but has not yet been verified in Session 0 on the user's PC.

## Suspend / Resume

In Portable, `PBT_APMSUSPEND` performs critical OFF **directly in the process**, without Named Pipe, network scanning, or long retries. It uses the known IP and a dedicated short timeout. Physical OFF does not clear temporary overrides such as `manual_day`: Sleep is not the same as the user's decision to leave that mode.

The suspend notice can arrive when Windows is already shutting down the network. The miIO client reuses a recent session to avoid a new handshake; if none exists, it tries one unicast handshake within the short budget. This reduces delay but cannot guarantee the lamp receives OFF if the connection disappears first. For a user-initiated suspend where turning off is a requirement, run `& ".\runtime\python.exe" .\sleepnow.py --mode portable --require-lamp-off` from Portable: the helper attempts OFF before requesting suspension and does not suspend without confirmation.

Suspension started from the Windows Start menu does not go through `sleepnow.py`: Portable only receives `PBT_APMSUSPEND` immediately before sleep, and LAN OFF is best effort. Service also receives the power event directly from SCM and does not depend on the session agent, but still cannot guarantee OFF if the network or lamp stops responding at that moment. To require OFF confirmation before suspend, use `sleepnow.py --require-lamp-off` in the mode you are running.

Do not run Portable and an older installation that controls the same lamp at the same time. Before testing Suspend, confirm the Portable runtime responds to `runtime-status`; if the Pipe stops responding, close the old Portable process and restart it from a normal interactive session.

To test local changes before a PR, keep `config.json`, `secrets/`, `data/`, and `logs/` outside the repository. Use a separate `MijiaLamp-Portable-Dev` folder, close the old Portable from its tray icon, and run `scripts/update-portable-dev.ps1` from the repository. The script updates Dev code and preserves its runtime, configuration, token, and state. Start Dev from a normal PowerShell session and confirm that `pythonw.exe` uses that folder's runtime; `runtime-status` alone may respond from another instance because both share the same Pipe.

In Service mode, SCM remains the primary authority for power events. The Agent's one-way hint has a monotonic deadline so a message held during Sleep cannot become a stale OFF after Resume.

`PBT_APMRESUMEAUTOMATIC` and `PBT_APMRESUMESUSPEND` invalidate previous work by incrementing `intent_revision`, but never set `display_on=True` or `user_presence=present`.

Turning back on requires a real interactive signal, mainly Display ON. An automatic maintenance wake therefore does not turn on the lamp; if the user moves the mouse and the sign-in screen appears, the real Display ON can restore the previous profile even before Windows is unlocked.

## Modern Standby

Agent handlers stay very short. Display/WTS/Presence use one-way notifications. Portable Suspend uses synchronous OFF with a short timeout; Service also receives the power event directly from SCM.

## Sleep Now

`Sleep Now` requests OFF before calling `SetSuspendState`. The helper explicitly enables `SeShutdownPrivilege`. In Service mode it uses the service Pipe; in Portable it uses the Portable Pipe.
