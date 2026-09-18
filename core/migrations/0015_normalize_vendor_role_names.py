from django.db import migrations


def normalize_role_name(value):
    value = (value or "").strip()
    return value[:1].upper() + value[1:] if value else value


def normalize_vendor_roles(apps, schema_editor):
    Vendor = apps.get_model("core", "Vendor")
    VendorRole = apps.get_model("core", "VendorRole")

    for role in list(VendorRole.objects.all()):
        normalized_name = normalize_role_name(role.name)
        target = VendorRole.objects.filter(name=normalized_name).exclude(pk=role.pk).first()
        if target:
            for vendor in role.vendors.all():
                vendor.role_categories.add(target)
            role.delete()
        elif role.name != normalized_name:
            role.name = normalized_name
            role.save(update_fields=["name"])

    for vendor in Vendor.objects.all():
        normalized_roles = ", ".join(
            normalize_role_name(role)
            for role in (vendor.roles or "").split(",")
            if role.strip()
        )
        if vendor.roles != normalized_roles:
            vendor.roles = normalized_roles
            vendor.save(update_fields=["roles"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_copy_vendor_roles"),
    ]

    operations = [
        migrations.RunPython(normalize_vendor_roles, migrations.RunPython.noop),
    ]
