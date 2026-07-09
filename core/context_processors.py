from .models import TeamMemberProfile


def crm_permissions(request):
    """Adds CRM permission flags for templates."""
    user = request.user
    profile = None

    if getattr(user, "is_authenticated", False):
        try:
            profile = user.crm_profile
        except TeamMemberProfile.DoesNotExist:
            profile = None

    return {
        "crm_permissions": {
            "can_view_clients": bool(profile and profile.can_view_clients),
            "can_view_analytics": bool(profile and profile.can_view_analytics),
            "can_manage_system": bool(profile and profile.can_manage_system),
            "is_staff": user.is_authenticated and user.is_staff,
        }
    }
