from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import read_device_cache, update_device_cache, update_lamp_ip
from .errors import CommunicationError, DeviceMismatchError
from .paths import TOKEN_PATH
from .secrets_store import SCOPE_LOCAL_MACHINE, load_token
from .transport import LampPhysicalState, ProfileValues
from .util import epoch_now, redact_secrets


def _import_device():
    try:
        from miio import Device
    except Exception as exc:
        raise CommunicationError("No se pudo importar python-miio. Ejecutá install.ps1 nuevamente.") from exc
    return Device


def _extract_model(info) -> str:
    return str(getattr(info, "model", None) or "")


def _handshake_did(response) -> str:
    try:
        raw = response.header.value.device_id
        return str(int.from_bytes(raw, byteorder="big"))
    except Exception:
        return ""


def _normalize_mac(value: str) -> str:
    return value.replace("-", ":").upper().strip()


class MiioLampClient:
    """python-miio transport isolated behind the LampTransport protocol."""

    def __init__(self, cfg: dict, logger, *, token_scope: str = SCOPE_LOCAL_MACHINE):
        self.cfg = cfg
        self.log = logger
        self.token_scope = token_scope
        self._token_cache: str | None = None
        self._token_mtime_ns: int | None = None

    @property
    def token(self) -> str:
        try:
            mtime = TOKEN_PATH.stat().st_mtime_ns
        except OSError:
            mtime = None
        if self._token_cache is None or mtime != self._token_mtime_ns:
            self._token_cache = load_token(expected_scope=self.token_scope)
            self._token_mtime_ns = mtime
        return self._token_cache

    def _device(self, ip: str, timeout: float | None = None):
        Device = _import_device()
        return Device(
            ip=str(ip),
            token=self.token,
            timeout=float(timeout if timeout is not None else self.cfg["miio_timeout_seconds"]),
            lazy_discover=True,
        )

    def probe_identity(self, ip: str, timeout: float | None = None) -> tuple[str, str]:
        dev = self._device(ip, timeout)
        try:
            info = dev.info()
            model = _extract_model(info)
            did = str(dev.device_id)
        except Exception as exc:
            raise CommunicationError(
                f"miIO no respondió correctamente en {ip}: {redact_secrets(exc)}"
            ) from exc

        expected_model = str(self.cfg["expected_model"])
        expected_did = str(self.cfg["device_id"])
        if model != expected_model:
            raise DeviceMismatchError(
                f"El dispositivo en {ip} reportó modelo {model!r}; esperaba {expected_model!r}"
            )
        if did != expected_did:
            raise DeviceMismatchError(
                f"El dispositivo en {ip} reportó DID {did!r}; esperaba {expected_did!r}"
            )
        return model, did

    def read_state(self, ip: str | None = None, timeout: float | None = None) -> LampPhysicalState:
        ip = str(ip or self.cfg["lamp_ip"])
        dev = self._device(ip, timeout)
        try:
            values = dev.send("get_prop", ["power", "bright", "ct"], retry_count=1)
        except Exception as exc:
            raise CommunicationError(f"No pude leer el estado físico en {ip}: {redact_secrets(exc)}") from exc
        if not isinstance(values, (list, tuple)) or not values:
            raise CommunicationError(f"Respuesta get_prop inesperada desde {ip}: {values!r}")
        power = str(values[0]).lower() if values[0] is not None else None
        try:
            brightness = int(values[1]) if len(values) > 1 and values[1] is not None else None
        except (TypeError, ValueError):
            brightness = None
        try:
            kelvin = int(values[2]) if len(values) > 2 and values[2] is not None else None
        except (TypeError, ValueError):
            kelvin = None
        return LampPhysicalState(power, brightness, kelvin, ip)

    def set_power(self, power: str, *, ip: str | None = None, fast: bool = False) -> None:
        ip = str(ip or self.cfg["lamp_ip"])
        timeout = float(self.cfg["miio_fast_timeout_seconds"] if fast else self.cfg["miio_timeout_seconds"])
        dev = self._device(ip, timeout)
        transition = 0 if fast else int(self.cfg.get("power_transition_ms", 0))
        params = [power] if transition <= 0 else [power, "smooth", transition]
        try:
            dev.send("set_power", params, retry_count=1 if fast else int(self.cfg.get("retries", 2)))
        except Exception as exc:
            raise CommunicationError(f"Falló set_power({power}) en {ip}: {redact_secrets(exc)}") from exc

    def set_power_critical_off(self, *, ip: str | None = None, timeout: float = 0.25) -> None:
        """Best-effort OFF for Suspend: fixed IP, no discovery, no retries, hard timeout."""
        ip = str(ip or self.cfg["lamp_ip"])
        dev = self._device(ip, float(timeout))
        try:
            dev.send("set_power", ["off"], retry_count=0)
        except Exception as exc:
            raise CommunicationError(f"Falló OFF crítico en {ip}: {redact_secrets(exc)}") from exc

    def apply_profile(self, profile: ProfileValues, *, ip: str | None = None, fast: bool = False) -> None:
        ip = str(ip or self.cfg["lamp_ip"])
        timeout = float(self.cfg["miio_fast_timeout_seconds"] if fast else self.cfg["miio_timeout_seconds"])
        dev = self._device(ip, timeout)
        transition = 0 if fast else int(self.cfg.get("profile_transition_ms", 700))
        try:
            if transition > 0:
                try:
                    dev.send("set_ct_abx", [profile.kelvin, "smooth", transition], retry_count=1)
                except Exception:
                    dev.send("set_ct_abx", [profile.kelvin, "sudden", 0], retry_count=1)
                time.sleep(0.05)
                try:
                    dev.send("set_bright", [profile.brightness, "smooth", transition], retry_count=1)
                except Exception:
                    dev.send("set_bright", [profile.brightness], retry_count=1)
            else:
                dev.send("set_ct_abx", [profile.kelvin, "sudden", 0], retry_count=1)
                dev.send("set_bright", [profile.brightness], retry_count=1)
        except Exception as exc:
            raise CommunicationError(
                f"Falló aplicar perfil {profile.name} ({profile.kelvin}K/{profile.brightness}%) "
                f"en {ip}: {redact_secrets(exc)}"
            ) from exc

    def _probe_handshake_did(self, ip: str, timeout: float) -> str | None:
        Device = _import_device()
        try:
            dev = Device(ip=str(ip), token=self.token, timeout=float(timeout), lazy_discover=True)
            response = dev.send_handshake()
            return _handshake_did(response) or None
        except Exception:
            return None

    def _neighbor_candidates(self) -> list[str]:
        if os.name != "nt" or not bool(self.cfg.get("discovery_neighbor_enabled", True)):
            return []
        cache = read_device_cache()
        expected = _normalize_mac(str(self.cfg.get("expected_mac", "") or cache.get("observed_mac", "")))
        if not expected:
            return []
        script = (
            "Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
            "Where-Object { $_.State -ne 'Unreachable' } | "
            'ForEach-Object { "$($_.IPAddress)|$($_.LinkLayerAddress)" }'
        )
        try:
            cp = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=4,
                creationflags=0x08000000,
                check=False,
            )
            result: list[str] = []
            for line in cp.stdout.splitlines():
                if "|" not in line:
                    continue
                ip, mac = line.strip().split("|", 1)
                if _normalize_mac(mac) == expected:
                    try:
                        ipaddress.IPv4Address(ip)
                    except ValueError:
                        continue
                    result.append(ip)
            return result
        except Exception as exc:
            self.log.debug("Get-NetNeighbor no disponible: %s", exc)
            return []

    def _mdns_candidates(self, timeout: float) -> list[str]:
        try:
            from miio.discovery import Discovery

            found = Discovery.discover_mdns(timeout=float(timeout))
            return list(found.keys())
        except Exception as exc:
            self.log.info("mDNS discovery no disponible/falló: %s", exc)
            return []

    def _local_scan_network(self) -> ipaddress.IPv4Network | None:
        target = str(self.cfg["lamp_ip"])
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((target, 54321))
            return ipaddress.IPv4Network(f"{sock.getsockname()[0]}/24", strict=False)
        except OSError:
            try:
                ips = socket.gethostbyname_ex(socket.gethostname())[2]
                ip = next(x for x in ips if not x.startswith(("127.", "169.254.")))
                return ipaddress.IPv4Network(f"{ip}/24", strict=False)
            except Exception:
                return None
        finally:
            sock.close()

    def _accept_candidate(self, ip: str, old_ip: str, source: str) -> str | None:
        try:
            model, did = self.probe_identity(ip, timeout=1.25)
        except (CommunicationError, DeviceMismatchError):
            return None
        self.log.info("Discovery %s validó %s model=%s did=%s", source, ip, model, did)
        if ip != old_ip:
            update_lamp_ip(ip)
            self.cfg["lamp_ip"] = ip
        update_device_cache(last_discovery_success_at=epoch_now(), consecutive_discovery_failures=0)
        return ip

    def discover(self, *, force: bool = False) -> str | None:
        if not bool(self.cfg.get("discovery_enabled", True)):
            return None
        now = epoch_now()
        cache = read_device_cache()
        base_cooldown = float(self.cfg.get("discovery_cooldown_seconds", 300))
        failures = max(0, int(cache.get("consecutive_discovery_failures", 0) or 0))
        max_backoff = float(self.cfg.get("discovery_backoff_max_seconds", 1800))
        cooldown = min(max_backoff, base_cooldown * (2 ** min(failures, 6))) if base_cooldown > 0 else 0.0
        last = float(cache.get("last_discovery_attempt_at", 0) or 0)
        if not force and last > 0 and now - last < cooldown:
            self.log.info(
                "Discovery omitido por backoff (%ss restantes; failures=%s)",
                int(cooldown - (now - last)),
                failures,
            )
            return None
        update_device_cache(last_discovery_attempt_at=now)

        old_ip = str(self.cfg["lamp_ip"])
        self.log.info("Discovery iniciado; IP=%s DID=%s", old_ip, self.cfg["device_id"])

        # 1) Windows neighbor table, when a known MAC is configured.
        for ip in self._neighbor_candidates():
            found = self._accept_candidate(ip, old_ip, "neighbor")
            if found:
                return found

        # 2) mDNS.
        for ip in self._mdns_candidates(float(self.cfg.get("discovery_mdns_seconds", 2.0))):
            found = self._accept_candidate(ip, old_ip, "mDNS")
            if found:
                return found

        # 3) /24 is expensive and has its own longer cooldown.
        if bool(self.cfg.get("discovery_scan_enabled", True)):
            full_cd = float(self.cfg.get("discovery_full_scan_cooldown_seconds", 1800))
            last_full = float(cache.get("last_full_scan_at", 0) or 0)
            if force or last_full <= 0 or now - last_full >= full_cd:
                update_device_cache(last_full_scan_at=now)
                network = self._local_scan_network()
                if network is not None:
                    timeout = float(self.cfg.get("discovery_scan_timeout_seconds", 0.4))
                    workers = int(self.cfg.get("discovery_scan_workers", 16))
                    candidates = [str(ip) for ip in network.hosts() if str(ip) != old_ip]
                    self.log.info("Discovery /24 %s: %d hosts, %d workers", network, len(candidates), workers)
                    expected_did = str(self.cfg["device_id"])
                    with ThreadPoolExecutor(max_workers=workers) as pool:
                        futures = {
                            pool.submit(self._probe_handshake_did, ip, timeout): ip for ip in candidates
                        }
                        for future in as_completed(futures):
                            ip = futures[future]
                            try:
                                if future.result() != expected_did:
                                    continue
                            except Exception:
                                continue
                            found = self._accept_candidate(ip, old_ip, "/24")
                            if found:
                                return found
            else:
                self.log.info("Scan /24 omitido por full-scan cooldown")

        failures = int(cache.get("consecutive_discovery_failures", 0) or 0) + 1
        update_device_cache(consecutive_discovery_failures=failures, last_discovery_failure_at=now)
        self.log.warning("Discovery finalizó sin encontrar el dispositivo esperado")
        return None

    def network_changed(self) -> None:
        """Clear discovery throttles after a Windows network/interface change."""
        update_device_cache(
            last_discovery_attempt_at=0.0,
            last_full_scan_at=0.0,
            consecutive_discovery_failures=0,
        )
        self.log.info("Cambio de red detectado; cooldowns de discovery reiniciados")

    def ensure_reachable(self, wait_seconds: float, *, allow_discovery: bool = True) -> str:
        deadline = time.monotonic() + max(0.0, float(wait_seconds))
        ip = str(self.cfg["lamp_ip"])
        discovery_done = False
        last_error: Exception | None = None
        delay = 0.25

        while True:
            try:
                self.probe_identity(ip)
                return ip
            except (CommunicationError, DeviceMismatchError) as exc:
                last_error = exc

            if allow_discovery and not discovery_done:
                discovery_done = True
                found = self.discover()
                if found:
                    ip = found
                    try:
                        self.probe_identity(ip)
                        return ip
                    except (CommunicationError, DeviceMismatchError) as exc:
                        last_error = exc

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(delay, remaining))
            delay = min(2.0, delay * 2)

        raise CommunicationError(
            f"La lámpara no quedó disponible dentro de {wait_seconds}s ({redact_secrets(last_error)})"
        )
