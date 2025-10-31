import sys, os, importlib
admin_path = "/etc/secrets/admin_commands.py"
if os.path.exists(admin_path):
    sys.path.append("/etc/secrets")
    try:
        import admin_commands
        importlib.reload(admin_commands)
        print("[ADMIN] admin_commands loaded successfully")
    except Exception as e:
        print("[ADMIN] Failed to load admin_commands:", e)
else:
    print("[ADMIN] admin_commands.py not found in /etc/secrets")



