"""
Alerting for the WhatsApp Agent Platform.

Alerts are evaluated by AlertManager.check_all() and dispatched via Telegram
(primary) with an email fallback. Every evaluation is also logged (so Sentry /
log-based alerting works) regardless of delivery channel availability.

Alert conditions implemented:
  - bridge_down            : WhatsApp bridge connector is not connected/fresh
  - dead_letter_growing    : number of dead-letter items above threshold
  - db_pool_exhausted      : DB pool utilisation above threshold
  - whatsapp_session_expired : connector session/QR expired
  - llm_latency_high       : p95 LLM latency above threshold
  - error_rate_high        : overall 5xx error rate above threshold
  - quota_near_limit       : a client is within threshold_pct of any quota

Thresholds and channels come from settings (config.Settings) when available,
otherwise from env vars / sensible defaults.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from logging_setup import get_logger

logger = get_logger("alerts")

SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


@dataclass
class Alert:
    name: str
    severity: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
        }


@dataclass
class AlertThresholds:
    bridge_stale_minutes: int = 3
    dead_letter_count: int = 25
    db_pool_pct: int = 90
    llm_p95_ms: float = 4000.0
    error_rate_pct: int = 5
    quota_pct: int = 90


def _load_thresholds() -> AlertThresholds:
    return AlertThresholds(
        bridge_stale_minutes=int(os.getenv("ALERT_BRIDGE_STALE_MIN", "3")),
        dead_letter_count=int(os.getenv("ALERT_DEAD_LETTER", "25")),
        db_pool_pct=int(os.getenv("ALERT_DB_POOL_PCT", "90")),
        llm_p95_ms=float(os.getenv("ALERT_LLM_P95_MS", "4000")),
        error_rate_pct=int(os.getenv("ALERT_ERROR_RATE_PCT", "5")),
        quota_pct=int(os.getenv("ALERT_QUOTA_PCT", "90")),
    )


class AlertManager:
    """Evaluates alert conditions and dispatches notifications."""

    def __init__(self, thresholds: Optional[AlertThresholds] = None,
                 telegram_fn: Optional[Callable[[str, Optional[str]], bool]] = None,
                 email_fn: Optional[Callable[[str, str, str, str], bool]] = None,
                 dry_run: bool = False) -> None:
        self.thresholds = thresholds or _load_thresholds()
        self.dry_run = dry_run
        self._telegram_fn = telegram_fn
        self._email_fn = email_fn
        self.last_alerts: List[Alert] = []
        self.last_check = ""

    # -- condition evaluators ----------------------------------------------

    def check_bridge(self, connector: Any = None, status: Optional[Dict[str, Any]] = None) -> Optional[Alert]:
        """Alert if the WhatsApp bridge is disconnected or stale."""
        status = status or self._safe_connector_status(connector)
        if not status:
            return None
        connected = bool(status.get("connected", False))
        last_seen = status.get("last_seen")
        stale = False
        if last_seen:
            try:
                from datetime import timedelta
                ls = datetime.fromisoformat(last_seen) if isinstance(last_seen, str) else last_seen
                if (datetime.now(timezone.utc) - ls).total_seconds() > self.thresholds.bridge_stale_minutes * 60:
                    stale = True
            except Exception:
                stale = True
        if not connected:
            return Alert("bridge_down", "critical",
                         "WhatsApp bridge is disconnected",
                         {"status": status})
        if stale:
            return Alert("bridge_down", "warning",
                         "WhatsApp bridge has not reported recently",
                         {"last_seen": last_seen})
        return None

    def check_session(self, connector: Any = None, status: Optional[Dict[str, Any]] = None) -> Optional[Alert]:
        """Alert if the WhatsApp session/QR has expired."""
        status = status or self._safe_connector_status(connector)
        if not status:
            return None
        if status.get("session_expired") or (status.get("status") in ("qr_expired", "logged_out", "expired")):
            return Alert("whatsapp_session_expired", "critical",
                         "WhatsApp session expired — manual re-auth required",
                         {"status": status})
        return None

    def check_dead_letters(self, count: int = 0) -> Optional[Alert]:
        if count >= self.thresholds.dead_letter_count:
            return Alert("dead_letter_growing", "warning",
                         f"Dead-letter queue is growing ({count} items)",
                         {"count": count,
                          "threshold": self.thresholds.dead_letter_count})
        return None

    def check_db_pool(self, used: int = 0, total: int = 0,
                      utilisation_pct: Optional[float] = None) -> Optional[Alert]:
        if utilisation_pct is None and total:
            utilisation_pct = (used / total * 100) if total else 0.0
        if utilisation_pct is None:
            return None
        if utilisation_pct >= self.thresholds.db_pool_pct:
            return Alert("db_pool_exhausted", "critical",
                         f"DB connection pool utilisation at {utilisation_pct:.0f}%",
                         {"used": used, "total": total,
                          "utilisation_pct": round(utilisation_pct, 1)})
        return None

    def check_llm_latency(self, latency_summary: Optional[Dict[str, Any]] = None) -> Optional[Alert]:
        try:
            from metrics import metrics_collector
        except Exception:
            metrics_collector = None  # type: ignore
        if latency_summary is None and metrics_collector is not None:
            latency_summary = metrics_collector.get_llm_latency(hours=1)
        if not latency_summary:
            return None
        p95 = float(latency_summary.get("p95", 0) or 0)
        if p95 >= self.thresholds.llm_p95_ms:
            return Alert("llm_latency_high", "warning",
                         f"LLM p95 latency high ({p95}ms)",
                         latency_summary)
        return None

    def check_error_rate(self, error_summary: Optional[Dict[str, Any]] = None) -> Optional[Alert]:
        try:
            from metrics import metrics_collector
        except Exception:
            metrics_collector = None  # type: ignore
        if error_summary is None and metrics_collector is not None:
            error_summary = metrics_collector.get_error_rates()
        if not error_summary:
            return None
        rate = float(error_summary.get("overall_error_rate", 0) or 0)
        if rate >= self.thresholds.error_rate_pct:
            return Alert("error_rate_high", "critical",
                         f"Overall 5xx error rate at {rate}%",
                         error_summary)
        return None

    def check_quotas(self, client_ids: Optional[List[int]] = None) -> List[Alert]:
        try:
            from usage_metering import usage_meter
        except Exception:
            usage_meter = None  # type: ignore
        if usage_meter is None:
            return []
        out: List[Alert] = []
        if client_ids is None:
            try:
                client_ids = list(usage_meter.get_all_clients_usage().keys())
            except Exception:
                client_ids = []
        for cid in client_ids:
            try:
                violations = usage_meter.check_quotas(cid, period="month",
                                                     threshold_pct=self.thresholds.quota_pct)
                for v in violations:
                    out.append(Alert(
                        "quota_near_limit", "warning",
                        f"Client {cid} near quota on {v['metric']} ({v['percent']}%)",
                        v,
                    ))
            except Exception as e:  # pragma: no cover
                logger.debug("quota check failed for client %s: %s", cid, e)
        return out

    # -- dispatch -----------------------------------------------------------

    @staticmethod
    def _in_quiet_hours(now: Optional["datetime"] = None) -> bool:
        """Return True if the current wall-clock time falls inside configured
        alert quiet hours (ALERT_QUIET_HOURS_START / ALERT_QUIET_HOURS_END, HH:MM
        in 24h format). When no quiet hours are configured, returns False.
        """
        start = os.getenv("ALERT_QUIET_HOURS_START")
        end = os.getenv("ALERT_QUIET_HOURS_END")
        if not start or not end:
            return False
        try:
            now = now or datetime.now(timezone.utc)
            minutes = now.hour * 60 + now.minute
            s_h, s_m = (int(x) for x in start.split(":"))
            e_h, e_m = (int(x) for x in end.split(":"))
            s = s_h * 60 + s_m
            e = e_h * 60 + e_m
            if s <= e:  # same-day window
                return s <= minutes < e
            # window crosses midnight (e.g. 22:00 -> 06:00)
            return minutes >= s or minutes < e
        except (ValueError, TypeError, AttributeError):
            return False

    def dispatch(self, alert: Alert) -> bool:
        """Send an alert via Telegram (primary) + email (fallback). Always logs."""
        text = self._format(alert)
        if alert.severity == "info":
            logger.info("ALERT[%s] %s", alert.name, alert.message)
        elif alert.severity == "warning":
            logger.warning("ALERT[%s] %s", alert.name, alert.message)
        else:
            logger.error("ALERT[%s] %s", alert.name, alert.message)
        if self.dry_run:
            return True
        # Quiet hours: hold non-critical alerts until morning, but always log.
        if self._in_quiet_hours() and alert.severity != "critical":
            logger.info(
                "ALERT[%s] suppressed during quiet hours (severity=%s): %s",
                alert.name, alert.severity, alert.message,
            )
            return True
        sent = False
        try:
            if self._telegram_fn is not None:
                sent = bool(self._telegram_fn(text, None))
            else:
                sent = self._send_telegram(text)
        except Exception as e:
            logger.error("telegram dispatch failed for %s: %s", alert.name, e)
        if not sent:
            try:
                if self._email_fn is not None:
                    self._email_fn("ops@platform.local", f"[ALERT] {alert.name}", text, text)
                else:
                    self._send_email(f"[ALERT] {alert.name}", text)
            except Exception as e:
                logger.error("email fallback failed for %s: %s", alert.name, e)
        return sent

    def check_all(self, context: Optional[Dict[str, Any]] = None) -> List[Alert]:
        """Run all checks, dispatch any triggered alerts, return them."""
        context = context or {}
        alerts: List[Alert] = []
        checks = [
            self.check_bridge(connector=context.get("connector"), status=context.get("bridge_status")),
            self.check_session(connector=context.get("connector"), status=context.get("bridge_status")),
            self.check_dead_letters(context.get("dead_letter_count", 0)),
            self.check_db_pool(
                used=context.get("db_pool_used", 0),
                total=context.get("db_pool_total", 0),
                utilisation_pct=context.get("db_pool_pct"),
            ),
            self.check_llm_latency(context.get("llm_latency")),
            self.check_error_rate(context.get("error_rates")),
        ]
        for a in checks:
            if a is not None:
                alerts.append(a)
        alerts.extend(self.check_quotas(context.get("client_ids")))
        self.last_alerts = alerts
        self.last_check = datetime.now(timezone.utc).isoformat()
        for a in alerts:
            self.dispatch(a)
        return alerts

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _safe_connector_status(connector: Any) -> Optional[Dict[str, Any]]:
        if connector is None:
            return None
        try:
            getter = getattr(connector, "status", None) or getattr(connector, "get_status", None)
            if callable(getter):
                return getter() if getter.__name__ == "status" else getter()
        except Exception as e:
            logger.debug("connector status failed: %s", e)
        for attr in ("connected", "last_seen", "session_expired", "status"):
            if hasattr(connector, attr):
                try:
                    return {attr: getattr(connector, attr)}
                except Exception:
                    continue
        return None

    @staticmethod
    def _format(alert: Alert) -> str:
        return (f"🚨 [{alert.severity.upper()}] {alert.name}\n"
                f"{alert.message}\n"
                f"time={alert.timestamp}")

    def _send_telegram(self, text: str) -> bool:
        try:
            from handoff import send_telegram_message
            return bool(send_telegram_message(text, None))
        except Exception as e:
            logger.debug("lazy telegram send failed: %s", e)
            return False

    def _send_email(self, subject: str, text: str) -> bool:
        try:
            from email_auth import EmailService
            svc = EmailService()
            return bool(svc.send_email("ops@platform.local", subject, text, text))
        except Exception as e:
            logger.debug("lazy email send failed: %s", e)
            return False


# Global manager (dry_run until wiring is confirmed in main.py)
alert_manager = AlertManager(dry_run=os.getenv("ALERT_DRY_RUN", "true").lower() == "true")
