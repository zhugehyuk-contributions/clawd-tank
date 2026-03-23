"""Bonjour/mDNS service registration and discovery for Clawd Tank network mode."""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("clawd-tank.bonjour")

SERVICE_TYPE = "_clawd-tank._tcp."
SERVICE_DOMAIN = ""

_PYOBJC_AVAILABLE = False
try:
    from Foundation import NSNetService, NSNetServiceBrowser, NSRunLoop, NSDate
    _PYOBJC_AVAILABLE = True
except ImportError:
    logger.debug("pyobjc not available — Bonjour disabled")


class BonjourService:
    """Registers and discovers Clawd Tank network servers via mDNS/Bonjour."""

    def __init__(self):
        self._service: Optional[object] = None
        self._browser: Optional[object] = None
        self._discovered: list[dict] = []

    @staticmethod
    def is_available() -> bool:
        """Check if Bonjour (pyobjc) is available on this system."""
        return _PYOBJC_AVAILABLE

    def register(self, port: int, hostname: str) -> bool:
        """Register a Bonjour service. Returns True on success."""
        if not _PYOBJC_AVAILABLE:
            logger.warning("Bonjour: pyobjc not available, skipping registration")
            return False
        try:
            self._service = NSNetService.alloc().initWithDomain_type_name_port_(
                SERVICE_DOMAIN, SERVICE_TYPE, hostname, port
            )
            self._service.publish()
            logger.info("Bonjour: registered %s on port %d", hostname, port)
            return True
        except Exception:
            logger.exception("Bonjour: registration failed")
            self._service = None
            return False

    def unregister(self) -> None:
        """Unregister the Bonjour service."""
        if self._service:
            try:
                self._service.stop()
            except Exception:
                pass
            self._service = None
            logger.info("Bonjour: unregistered")

    async def discover(self, timeout: float = 3.0) -> list[dict]:
        """Discover Clawd Tank servers on the local network.

        Returns list of dicts: [{"hostname": str, "host": str, "port": int}]
        """
        if not _PYOBJC_AVAILABLE:
            logger.debug("Bonjour: pyobjc not available, no discovery")
            return []

        self._discovered = []
        found_services = []

        class BrowserDelegate:
            def netServiceBrowser_didFindService_moreComing_(self, browser, service, more):
                found_services.append(service)

        try:
            delegate = BrowserDelegate()
            browser = NSNetServiceBrowser.alloc().init()
            browser.setDelegate_(delegate)
            browser.searchForServicesOfType_inDomain_(SERVICE_TYPE, SERVICE_DOMAIN)

            # Run the run loop for timeout seconds to collect results
            end_time = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < end_time:
                NSRunLoop.currentRunLoop().runUntilDate_(
                    NSDate.dateWithTimeIntervalSinceNow_(0.1)
                )
                await asyncio.sleep(0.05)

            browser.stop()

            # Resolve found services
            results = []
            for svc in found_services:
                svc.resolveWithTimeout_(2.0)
                NSRunLoop.currentRunLoop().runUntilDate_(
                    NSDate.dateWithTimeIntervalSinceNow_(2.0)
                )
                host = str(svc.hostName()) if svc.hostName() else None
                port = svc.port()
                name = str(svc.name())
                if host and port > 0:
                    results.append({
                        "hostname": name,
                        "host": host.rstrip("."),
                        "port": port,
                    })

            logger.info("Bonjour: discovered %d servers", len(results))
            return results

        except Exception:
            logger.exception("Bonjour: discovery failed")
            return []
