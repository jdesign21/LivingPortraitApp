# LivingPortraitApp UI Password and Authentication

UI Password controls whether the web interface requires an administrator login. It defaults to **No**. Disabling UI Password does not delete an existing administrator account; credentials remain stored so authentication can be re-enabled later.

During initial setup, choose **No** to finish without creating an account. Choose **Yes** to create an administrator username and password at the final setup step. When enabling UI Password later from Account & Security, an existing account is reused. If no account exists, the application directs you to create one before requiring sign-in.

Changing UI Password takes effect immediately and does not require a reboot. Existing installations that do not yet have the UI Password setting default to **No** after upgrading, so upgrading does not force account creation or login.

## Administrator Password Recovery

If the administrator password is forgotten, sign in to the Raspberry Pi operating-system account locally or over SSH. Run:

```bash
~/flask_venv/bin/python ~/flask_ui/reset_admin_password.py
sudo systemctl restart flask_ui
```

The script prompts for a new password and stores only a password hash. Run it as the same Linux account that runs the Flask service so it can access `~/.livingportrait_auth/auth.json`.

The administrator credentials and automatically generated Flask signing key are stored in `~/.livingportrait_auth/`, outside the replaceable application files. The directory is restricted to the service account.

**Transport security note:** the current application server uses HTTP on port 5000. HTTP does not encrypt passwords or session cookies while they travel across the network. Use only on a trusted home LAN; HTTPS/reverse-proxy configuration should be a separate follow-up before exposing the app to untrusted networks.
