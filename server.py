import sys, os, importlib
admin_path = "/etc/secrets/admin_commands.py"
if os.path.exists(admin_path):
    sys.path.append("/etc/secrets")
    try:
        import types
        spec = importlib.util.spec_from_file_location("admin_commands", admin_path)
        admin_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(admin_module)
        if hasattr(admin_module, "init_admin"):
            admin_module.init_admin(app, rooms)
        print("[ADMIN] admin_commands loaded successfully")
    except Exception as e:
        print("[ADMIN] Failed to load admin_commands:", e)
else:
    print("[ADMIN] admin_commands.py not found in /etc/secrets")


