# Optional dedicated-account setup

This is an advanced, manual Linux setup. It is not required for ordinary doorbell
notifications, and does not require a camera. Review and adapt every command for
your host. Applying device rules requires administrator access and temporarily
interrupts microphone detection. Do not change a microphone shared by other apps.

Linux grants device access to accounts, not Python filenames. The approach here
uses a non-login account only for the root-owned detector, restricts its USB mic
to that account's group, and adds a systemd sandbox. Root administrators can still
override permissions. A compromised detector process still has microphone access;
this is not a guarantee against a fully compromised server.

## 1. Create a dedicated account and install root-owned files

Run from the repository root. The account/group names must not already exist;
review existing accounts instead of reusing them without checking their access.

```sh
sudo groupadd --system doorbell-detector
sudo useradd --system --gid doorbell-detector --home-dir /nonexistent \
  --no-create-home --shell /usr/sbin/nologin doorbell-detector
sudo install -d -o root -g doorbell-detector -m 750 /opt/doorbell-detector /etc/doorbell-detector
sudo install -o root -g doorbell-detector -m 640 detector.py profile.json /opt/doorbell-detector/
sudo install -o root -g doorbell-detector -m 640 privacy/config.example.json /etc/doorbell-detector/config.json
```

Create `/etc/doorbell-detector/notifier.env` with only the topic and publisher
credentials your ntfy instance needs. Do not copy subscriber credentials.
Set its owner/group to `root:doorbell-detector` and mode to `640`; edit the
configuration for your installation. The hardened service permits localhost
network traffic only, so its ntfy server must be local. Camera links are optional
and empty by default; see the main README if you want to configure one.

Do not grant the detector account extra groups such as `sudo`, `docker`, or the
shared `audio` group. Root-owned code prevents normal users from replacing the
program that the service launches. Other programs running as the dedicated
account would have the same device permissions, so keep it exclusive to this service.

## 2. Restrict the selected USB microphone

Locate your capture and control nodes with `arecord -l`. For example, to inspect
card 0's capture device (replace this path if your card number differs):

```sh
udevadm info --attribute-walk --name=/dev/snd/pcmC0D0c
```

Copy `microphone.rules.example` to a separate file and replace `VENDOR_ID` and
`PRODUCT_ID` with the USB device's `idVendor` and `idProduct`, not the USB host
controller's identifiers. The rule matches capture and mixer nodes, removes
automatic desktop access, and leaves other sound cards alone. It is named `71-`
to run after `70-uaccess` and before `73-seat-late`. Review these rule names on
your distribution. If multiple identical devices exist, add a suitable serial
match to avoid changing all of them.

After review, install the customised rule as
`/etc/udev/rules.d/71-doorbell-microphone.rules` with root ownership and mode `644`.
Stop the old user service before applying permissions: already-open capture
handles are not revoked merely by changing file permissions.

```sh
systemctl --user disable --now doorbell-detector.service
sudo udevadm control --reload-rules
sudo udevadm trigger --action=change /sys/class/sound/controlC0 /sys/class/sound/pcmC0D0c
sudo udevadm settle
```

Those two trigger paths are examples; use your selected microphone's actual
nodes. Check their group is `doorbell-detector` and mode is `660` before starting
the new service. Review any pre-existing access ACLs that could grant other users
access; adding a udev rule does not prove all old ACL grants were removed.

## 3. Activate and verify the system service

```sh
sudo install -m 644 privacy/doorbell-detector.service /etc/systemd/system/doorbell-detector.service
sudo systemd-analyze verify /etc/systemd/system/doorbell-detector.service
sudo systemctl daemon-reload
sudo systemctl enable --now doorbell-detector.service
sudo systemctl status doorbell-detector.service
sudo journalctl -u doorbell-detector.service -n 20 --no-pager
```

The hardened service hides home directories, restricts filesystem writes, drops
capabilities, prevents privilege escalation, limits devices, and restricts network
traffic to localhost. Kernel/systemd support varies; inspect warnings and verify
effective restrictions on your host. This template does not silently fall back
to the original service if installation fails.

Verify the normal account cannot read/open the microphone and the dedicated
account can. Ring once, check exactly one notification, and test any optional
click link. Also test reboot and USB reconnect behaviour.

Live capture does not save audio. Protect calibration recordings separately,
including copies on other machines or in backups. For strict account isolation,
use a private directory accessible only to root and the detector group; never
publish home recordings or notification credentials.

## Revert

Stop and disable the system service, move its unit and microphone rule out of
their active configuration directories, reload systemd/udev, and restore the
microphone's previous ownership, permissions, and ACLs. Then re-enable the
original user service. Keep backups of the original settings before applying
this recipe. Do not delete accounts, recordings, or credentials during rollback.

References: [systemd execution controls](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml)
and [udev rules](https://github.com/systemd/systemd/blob/main/man/udev.xml).
