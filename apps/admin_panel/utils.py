"""
Admin Panel — Utilities
=======================
Defines common helpers for admin logging, IP whitelisting, and audit trials.
"""

import logging
from .models import SystemLog, AdminLog

logger = logging.getLogger(__name__)


def syslog(level, category, message, **metadata):
    """
    Unified application-wide system logging helper.
    Saves to the database and duplicates to the standard logger for container logs.
    """
    try:
        SystemLog.objects.create(
            level=level,
            category=category,
            message=message,
            metadata=metadata if metadata else None
        )
    except Exception as e:
        logger.error("Failed to write to SystemLog: %s", str(e))
    
    # Log to container stdout/stderr
    log_func = getattr(logger, level.lower(), logger.info)
    log_func("[%s][%s] %s | Meta: %s", level, category, message, metadata)


def log_admin_action(admin_user, action, target_type, target_id, detail, request):
    """
    Audit logging helper for administrative actions.
    """
    # Resolve requester IP address
    ip_addr = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "0.0.0.0"))
    if ip_addr and "," in ip_addr:
        ip_addr = ip_addr.split(",")[0].strip()
        
    try:
        AdminLog.objects.create(
            admin_user=admin_user,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            detail=detail,
            ip_address=ip_addr
        )
        syslog(
            level="INFO",
            category="AUTH",
            message=f"Admin {admin_user.email if admin_user else 'System'} performed action: {action} on {target_type} {target_id}",
            detail=detail
        )
    except Exception as e:
        logger.error("Failed to write to AdminLog: %s", str(e))
