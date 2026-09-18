from django.db import migrations


def copy_vendor_roles(apps, schema_editor):
    Vendor = apps.get_model("core", "Vendor")
    VendorRole = apps.get_model("core", "VendorRole")

    for vendor in Vendor.objects.all():
        role_names = {role.strip() for role in (vendor.roles or "").split(",") if role.strip()}
        for role_name in role_names:
            role, _ = VendorRole.objects.get_or_create(name=role_name)
            vendor.role_categories.add(role)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_vendorrole_alter_vendor_roles_vendor_role_categories"),
    ]

    operations = [
        migrations.RunPython(copy_vendor_roles, migrations.RunPython.noop),
    ]
