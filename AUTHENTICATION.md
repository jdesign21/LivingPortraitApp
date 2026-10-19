# LivingPortraitApp Authentication Recovery

If the administrator password is forgotten, sign in to the Raspberry Pi operating-system account locally or over SSH. Run:

```bash
~/flask_venv/bin/python ~/flask_ui/reset_admin_password.py
sudo systemctl restart flask_ui
```

The script prompts for a new password and stores only a password hash. Run it as the same Linux account that runs the Flask service so it can access `~/.livingportrait_auth/auth.json`.

The administrator credentials and automatically generated Flask signing key are stored in `~/.livingportrait_auth/`, outside the replaceable application files. The directory is restricted to the service account.

**Transport security note:** the current application server uses HTTP on port 5000. HTTP does not encrypt passwords or session cookies while they travel across the network. Use only on a trusted home LAN; HTTPS/reverse-proxy configuration should be a separate follow-up before exposing the app to untrusted networks.
