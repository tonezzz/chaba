---
category: operations
---

# tony-dell PC Assessment

**Note**: This file contains static hardware specifications. For operational history and changes, see `hardware/tony-dell/changes.md`

Generated: 2026-07-08T13:36:47.999258+00:00 UTC

- **Machine:** tony-dell
- **Hostname:** tony-dell
- **User:** tony
- **Home:** /home/tony
- **Shell:** /bin/bash
- **Uptime:** 20:36:49 up 2 days,  6:16,  1 user,  load average: 2.43, 1.80, 1.28

## System

### OS Release

```
PRETTY_NAME="Ubuntu 26.04 LTS"
NAME="Ubuntu"
VERSION_ID="26.04"
VERSION="26.04 LTS (Resolute Raccoon)"
VERSION_CODENAME=resolute
ID=ubuntu
ID_LIKE=debian
HOME_URL="https://www.ubuntu.com/"
SUPPORT_URL="https://help.ubuntu.com/"
BUG_REPORT_URL="https://bugs.launchpad.net/ubuntu/"
PRIVACY_POLICY_URL="https://www.ubuntu.com/legal/terms-and-policies/privacy-policy"
UBUNTU_CODENAME=resolute
LOGO=ubuntu-logo
```

### hostnamectl

```
Static hostname: tony-dell
       Icon name: computer-desktop
         Chassis: desktop 🖥️
      Machine ID: f7a8ca6394d6455abb32db04c79fe35a
         Boot ID: d7b71f306c7344beb19c26cec77a6923
Operating System: Ubuntu 26.04 LTS
          Kernel: Linux 7.0.0-22-generic
    Architecture: x86-64
 Hardware Vendor: Dell Inc.
  Hardware Model: OptiPlex 7040
    Hardware SKU: 06B9
Hardware Version: A01
Firmware Version: 1.24.0
   Firmware Date: Thu 2022-07-14
    Firmware Age: 3y 11month 3w 4d
```

### Kernel

```
Linux tony-dell 7.0.0-22-generic #22-Ubuntu SMP PREEMPT_DYNAMIC Mon May 25 15:54:34 UTC 2026 x86_64 GNU/Linux
```
## Hardware

### Manufacturer

```
Dell Inc.
```

### Product Name

```
OptiPlex 7040
```

### Product Version

```

```

### Serial

```

```

### Chassis Type

```
3
```

### BIOS Date

```
07/14/2022
```

### BIOS Version

```
1.24.0
```

### CPU

```
Architecture:                            x86_64
CPU(s):                                  8
On-line CPU(s) list:                     0-7
Model name:                              Intel(R) Core(TM) i7-6700 CPU @ 3.40GHz
Thread(s) per core:                      2
Core(s) per socket:                      4
Socket(s):                               1
CPU(s) scaling MHz:                      74%
CPU max MHz:                             4000.0000
CPU min MHz:                             800.0000
NUMA node0 CPU(s):                       0-7
```

### Memory

```
total        used        free      shared  buff/cache   available
Mem:           7.1Gi       5.4Gi       260Mi       522Mi       2.2Gi       1.7Gi
Swap:           15Gi       3.0Gi        13Gi
```

### Disk Usage

```
Filesystem      Size  Used Avail Use% Mounted on
/dev/sda5       118G   41G   72G  37% /
```

### Block Devices

```
NAME     SIZE TYPE MOUNTPOINT                          MODEL
loop0   66.8M loop /snap/core24/1643                   
loop1     74M loop /snap/core22/2411                   
loop2      4K loop /snap/bare/5                        
loop3   47.9M loop /snap/cups/1206                     
loop4     20M loop /snap/desktop-security-center/151   
loop5   16.5M loop /snap/firmware-updater/226          
loop6  606.1M loop /snap/gnome-46-2404/153             
loop7   91.7M loop /snap/gtk-common-themes/1535        
loop8    395M loop /snap/mesa-2404/1165                
loop9   18.8M loop /snap/prompting-client/222          
loop10   402M loop /snap/mesa-2404/1781                
loop11  15.7M loop /snap/snap-store/1367               
loop12  49.3M loop /snap/snapd/26865                   
loop13  50.1M loop /snap/snapd/27406                   
loop14   828K loop /snap/snapd-desktop-integration/387 
sda    465.8G disk                                     ST500LM000-1EJ162
├─sda1   100M part /boot/efi                           
├─sda2    16M part                                     
├─sda3   200G part                                     
├─sda4   529M part                                     
├─sda5   120G part /                                   
└─sda6     8G part [SWAP]                              
sdb        0B disk                                     Mass-Storage
sdc        0B disk                                     Media-Player
sr0     1024M rom                                      PLDS DVD+/-RW DU-8A5LH
```

### GPU

```
00:02.0 VGA compatible controller: Intel Corporation Skylake-S GT2 [HD Graphics 530] (rev 06)
01:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Oland XT [Radeon HD 8670 / R5 340X OEM / R7 250/350/350X OEM] (rev 83)
```
## Network

### Interfaces

```
lo               UNKNOWN        127.0.0.1/8 ::1/128 
enp0s31f6        UP             192.168.1.42/24 2001:fb1:8d:f657:1642:244a:8516:cf8e/64 2001:fb1:8d:f657:7c40:fe4e:861d:d299/64 2001:fb1:8d:f657:c9d7:60a7:2ee3:82d6/64 fe80::2c01:1291:a04f:3e13/64 
wlx00761100125e  DOWN
```
## Installed Tools

### Ansible

```

```

### Python

```
Python 3.14.4
```

### Node

```
not installed
```

### npm

```
not installed
```

### VS Code

```

```

### Windsurf

```
1.110.1
16737566f57f3b53bde136375fe0544eca12fac4
```

### Chrome

```
Google Chrome 149.0.7827.200
```

### Docker

```
not installed
```

### Selected dpkg Packages

```
aglfn 1.7+git20191031.4036a9c-2build1
bash 5.3-2ubuntu1
bash-completion 1:2.16.0-8build1
chrome-remote-desktop 150.0.7871.19
curl 8.18.0-1ubuntu2.2
dmg2img 1.6.7+git20201227.a3e4134-0.1build1
dmidecode 3.6-2build1
firefox 1:1snap1-0ubuntu8
flameshot 13.3.0+git20251204-1
fonts-ubuntu 0.869+git20240321-0ubuntu2
gcc-15-base:amd64 15.2.0-16ubuntu1
gcc-16-base:amd64 16-20260322-1ubuntu1
geocode-glib-common 3.26.4-3
gir1.2-javascriptcoregtk-4.1:amd64 2.52.3-0ubuntu0.26.04.2
gir1.2-pango-1.0:amd64 1.57.0-1
git 1:2.53.0-1ubuntu1
git-man 1:2.53.0-1ubuntu1
google-chrome-stable 149.0.7827.200-1
gstreamer1.0-plugins-good:amd64 1.28.2-2
iso-codes 4.20.1-1
libargon2-1:amd64 0~20190702+dfsg-5
libavcodec62:amd64 7:8.0.1-3ubuntu2
libcairo-gobject2:amd64 1.18.4-3
libcairo-gobject-perl 1.005-4build4
libcodec2-1.2:amd64 1.2.0-4
libcpuinfo0:amd64 0.0~git20250905.877328f-1
libcurl3t64-gnutls:amd64 8.18.0-1ubuntu2.2
libcurl4t64:amd64 8.18.0-1ubuntu2.2
libencode-locale-perl 1.05-3
libgcc-s1:amd64 16-20260322-1ubuntu1
libgeocode-glib-2-0:amd64 3.26.4-3
libgoa-1.0-0b:amd64 3.58.0-1
libgoa-1.0-common 3.58.0-1
libgoa-backend-1.0-2:amd64 3.58.0-1
libgomp1:amd64 16-20260322-1ubuntu1
libharfbuzz-gobject0:amd64 12.3.2-2
libhttp-negotiate-perl 6.01-2
libjavascriptcoregtk-4.1-0:amd64 2.52.3-0ubuntu0.26.04.2
libjavascriptcoregtk-6.0-1:amd64 2.52.3-0ubuntu0.26.04.2
libkf6codecs6:amd64 6.24.0-0ubuntu1
libkf6codecs-data 6.24.0-0ubuntu1
libldacbt-abr2:amd64 2.0.2.3+git20200429+ed310a0-5build1
libldacbt-enc2:amd64 2.0.2.3+git20200429+ed310a0-5build1
libmarisa1:amd64 0.3.1+git20250817-1build1
libpagemaker-0.0-0:amd64 0.0.4-1build5
libpango-1.0-0:amd64 1.57.0-1
libpangocairo-1.0-0:amd64 1.57.0-1
libpangoft2-1.0-0:amd64 1.57.0-1
libpangoxft-1.0-0:amd64 1.57.0-1
libplist-2.0-4:amd64 2.7.0+git20250820-1build1
libplymouth5:amd64 24.004.60+git20250831.4a3c171d-0ubuntu8
libpolkit-gobject-1-0:amd64 127-2ubuntu1
libpthreadpool0:amd64 0.0~git20251020.0e6ca13-1
libpython3.14:amd64 3.14.4-1ubuntu0.1
libpython3.14-minimal:amd64 3.14.4-1ubuntu0.1
libpython3.14-stdlib:amd64 3.14.4-1ubuntu0.1
libpython3-stdlib:amd64 3.14.3-0ubuntu2
libqrencode4:amd64 4.1.1-2build1
librtmp1:amd64 2.4+20151223.gitfa8646d.1-3
libsignon-plugins-common1:amd64 8.61+git20231015.c8ad982-8
libsignon-qt6-1:amd64 8.61+git20231015.c8ad982-8
libspatialaudio0t64:amd64 0.3.0+git20180730+dfsg1-3
libuno-cppuhelpergcc3-3t64 4:26.2.4.2-0ubuntu0.26.04.1
libuno-purpenvhelpergcc3-3t64 4:26.2.4.2-0ubuntu0.26.04.1
libuno-salhelpergcc3-3t64 4:26.2.4.2-0ubuntu0.26.04.1
libx264-165:amd64 2:0.165.3222+gitb35605ac-3build1
libxnnpack0.20241108:amd64 0.0~git20241108.4ea82e5-2build1
linux-firmware 20260319.git217ca6e4.1ubuntu
linux-firmware-amd-graphics 20260319.git217ca6e4-0ubuntu3
linux-firmware-amd-misc 20260319.git217ca6e4-0ubuntu1
linux-firmware-broadcom-wireless 20260319.git217ca6e4-0ubuntu1
linux-firmware-intel-graphics 20260319.git217ca6e4-0ubuntu2
linux-firmware-intel-misc 20260319.git217ca6e4-0ubuntu1
linux-firmware-intel-wireless 20260319.git217ca6e4-0ubuntu2
linux-firmware-marvell-prestera 20260319.git217ca6e4-0ubuntu1
linux-firmware-marvell-wireless 20260319.git217ca6e4-0ubuntu1
linux-firmware-mediatek 20260319.git217ca6e4-0ubuntu1
linux-firmware-mellanox-spectrum 20260319.git217ca6e4-0ubuntu1
linux-firmware-misc 20260319.git217ca6e4-0ubuntu2
linux-firmware-netronome 20260319.git217ca6e4-0ubuntu1
linux-firmware-nvidia-graphics 20260319.git217ca6e4-0ubuntu1
linux-firmware-qlogic 20260319.git217ca6e4-0ubuntu1
linux-firmware-qualcomm-graphics 20260319.git217ca6e4-0ubuntu1
linux-firmware-qualcomm-misc 20260319.git217ca6e4-0ubuntu2
linux-firmware-qualcomm-wireless 20260319.git217ca6e4-0ubuntu1
linux-firmware-realtek 20260319.git217ca6e4-0ubuntu1
lshw 02.19.git.2021.06.19.996aaad9c7-2.1ubuntu3
makedumpfile 1:1.7.7-1
papirus-icon-theme 20250501+git20260316-0ubuntu1
plymouth 24.004.60+git20250831.4a3c171d-0ubuntu8
plymouth-label 24.004.60+git20250831.4a3c171d-0ubuntu8
plymouth-theme-lubuntu-logo 26.04.3
plymouth-theme-spinner 24.004.60+git20250831.4a3c171d-0ubuntu8
plymouth-theme-ubuntu-text 24.004.60+git20250831.4a3c171d-0ubuntu8
python3.14 3.14.4-1ubuntu0.1
python3.14-gdbm 3.14.4-1ubuntu0.1
python3.14-minimal 3.14.4-1ubuntu0.1
python3 3.14.3-0ubuntu2
python3-apport 2.34.0-0ubuntu2
python3-apt 3.1.0ubuntu1
python3-aptdaemon 2.0.2build1
python3-aptdaemon.gtk3widgets 2.0.2build1
python3-attr 25.4.0-1build1
python3-autocommand 2.2.2-4
python3-babel 2.17.0-2
python3-bcrypt 5.0.0-3build1
python3-blinker 1.9.0-2build1
python3-brlapi:amd64 6.7-1ubuntu6
python3-cairo 1.27.0-2build2
python3-certifi 2026.1.4+ds-1
python3-cffi-backend:amd64 2.0.0-3build1
python3-chardet 5.2.0+dfsg-2build1
python3-click 8.2.0+0.really.8.1.8-1build1
python3-commandnotfound 23.04.0build1
python3-configobj 5.0.9-1build1
python3-cryptography 46.0.5-1ubuntu2
python3-cups 2.0.4-3build1
python3-cupshelpers 1.5.18-4ubuntu2
python3-dasbus 1.7-2build1
python3-dbus 1.4.0-1build2
python3-dbus.mainloop.pyqt6 6.10.2-2build5
python3-debconf 1.5.92
python3-debian 1.0.1ubuntu2
python3-defer 1.0.6-2.1ubuntu2
python3-distro 1.9.0-1build1
python3-distro-info 1.15
python3-distupgrade 1:26.04.22
python3-gdbm 3.14.3-0ubuntu2
python3-gi 3.56.2-1
python3-gi-cairo 3.56.2-1
python3-httplib2 0.22.0-1build1
python3-ibus-1.0 1.5.34~rc2-1
python3-idna 3.11-1
python3-inflect 7.5.0-1build1
python3-jaraco.context 6.0.1-2
python3-jaraco.functools 4.1.0-1build1
python3-jaraco.text 4.0.0-1build1
python3-jinja2 3.1.6-1build1
python3-jsonpatch 1.32-6
python3-json-pointer 2.4-4
python3-jsonschema 4.19.2-6ubuntu2
python3-jsonschema-specifications 2023.12.1-4
python3-jwt 2.10.1-4ubuntu1
python3-launchpadlib 2.1.0-1build1
python3-lazr.restfulclient 0.14.6-3build1
python3-lazr.uri 1.0.6-7build1
python3-linkify-it 2.0.3-1ubuntu3
python3-louis 3.36.0-1
python3-markdown-it 3.0.0-3build1
python3-markupsafe 3.0.3-1build1
python3-mdurl 0.1.2-1build1
python3-minimal 3.14.3-0ubuntu2
python3-more-itertools 10.8.0-1build1
python3-netplan 1.2-1ubuntu5
python3-oauthlib 3.3.1-1build1
python3-olefile 0.47-1build1
python3-packaging 26.0-1
python3-passlib 1.9.3-1ubuntu1
python3-pexpect 4.9-4
python3-pil:amd64 12.1.1-2ubuntu1.2
python3-pkg-resources 78.1.1-0.1build1
python3-problem-report 2.34.0-0ubuntu2
python3-psutil 7.1.0-1ubuntu1
python3-ptyprocess 0.7.0-6build1
python3-pygments 2.19.2+dfsg-1
python3-pyparsing 3.3.2-2
python3-pyqt6 6.10.2-2build5
python3-pyqt6.qtqml 6.10.2-2build5
python3-pyqt6.qtquick 6.10.2-2build5
python3-pyqt6.sip 13.11.0-1build1
python3-referencing 0.36.2-1ubuntu2
python3-requests 2.32.5+dfsg-1ubuntu1
python3-rich 13.9.4-1.2
python3-rpds-py 0.27.1-2ubuntu3
python3-serial 3.5-2build1
python3-setproctitle:amd64 1.3.7-2build1
python3-setuptools 78.1.1-0.1build1
python3-software-properties 0.120
python3-speechd 0.12.1-2ubuntu1
python3-sss 2.12.0-1ubuntu5.1
python3-systemd 235-1build9
python3-typeguard 4.4.4-2
python3-typing-extensions 4.15.0-2
python3-uc-micro 1.0.3-1build1
python3-uno 4:26.2.4.2-0ubuntu0.26.04.1
python3-update-manager 1:26.04.5
python3-urllib3 2.6.3-1ubuntu1.1
python3-wadllib 2.0.0-3
python3-xdg 0.28-3
python3-xkit 0.5.0ubuntu8
python3-yaml 6.0.3-1build1
python3-zipp 3.23.0-1build1
qml6-module-sso-onlineaccounts:amd64 0.7+git20231028.05e79eb-7
qrencode 4.1.1-2build1
rust-coreutils 0.8.0-0ubuntu3
sddm 0.21.0+git20250502.4fe234b-2ubuntu3
signon-plugin-oauth2 0.25+git20231015.fab69886-3build1
vim 2:9.1.2141-1ubuntu4.6
vim-common 2:9.1.2141-1ubuntu4.6
vim-runtime 2:9.1.2141-1ubuntu4.6
vim-tiny 2:9.1.2141-1ubuntu4.6
wget 1.25.0-2ubuntu4
windsurf 3.4.22-1783128283
xfonts-efont-unicode 0.4.2-12build1
xfonts-efont-unicode-ib 0.4.2-12build1
xserver-xorg-video-intel 2:2.99.917+git20210115-1build2
```
## Development Environment

### Git Config

```
credential.helper=cache
```

### SSH Keys

```
total 56
drwx------  8 tony tony 4096 Jul  2 14:51 .
drwxr-x--- 27 tony tony 4096 Jul  7 08:09 ..
drwx------  2 tony tony 4096 Jun 27 13:56 agent
-rw-------  1 tony tony    0 Jun 19 16:00 authorized_keys
-rw-------  1 tony tony  399 Jul  2 14:11 id_cascade
-rw-r--r--  1 tony tony   89 Jul  2 14:11 id_cascade.pub
-rw-------  1 tony tony  399 Jun 25 14:40 id_ed25519
-rw-r--r--  1 tony tony   90 Jun 25 14:40 id_ed25519.pub
-rw-------  1 tony tony 2240 Jul  2 17:56 known_hosts
-rw-------  1 tony tony 2934 Jul  1 11:39 known_hosts.old
drwx------  2 tony tony 4096 Jun 29 13:48 ssh-copy-id.H8uzECMhZb
drwx------  2 tony tony 4096 Jun 29 13:48 ssh-copy-id.d7w5Erg0Dw
drwx------  2 tony tony 4096 Jun 29 13:48 ssh-copy-id.dgPi4GgEG3
drwx------  2 tony tony 4096 Jun 29 13:49 ssh-copy-id.diNoKnriGQ
drwx------  2 tony tony 4096 Jun 29 13:49 ssh-copy-id.rXxue6EgcK
```

### Projects

```
~/CascadeProjects
~/CascadeProjects/ans-fleet
~/CascadeProjects/devin-kb
~/CascadeProjects/notebook-server
```

### Git Repositories

```
~/CascadeProjects/ans-fleet
~/CascadeProjects/devin-kb
```

### Timezone

```
Local time: พ. 2026-07-08 20:36:48 +07
           Universal time: พ. 2026-07-08 13:36:48 UTC
                 RTC time: พ. 2026-07-08 13:36:48
                Time zone: Asia/Bangkok (+07, +0700)
System clock synchronized: yes
              NTP service: active
          RTC in local TZ: no
```

### Locale

```
System Locale: LANG=en_US.UTF-8
    VC Keymap: (unset)
   X11 Layout: us,th
    X11 Model: pc105
  X11 Variant: ,
  X11 Options: grp_led:scroll
```

### Running Services

```
UNIT                           LOAD   ACTIVE SUB     DESCRIPTION
  accounts-daemon.service        loaded active running Accounts Service
  avahi-daemon.service           loaded active running Avahi mDNS/DNS-SD Stack
  chrony.service                 loaded active running chrony, an NTP client/server
  colord.service                 loaded active running Manage, Install and Generate Color Profiles
  cron.service                   loaded active running Regular background program processing daemon
  cups-browsed.service           loaded active running Make remote CUPS printers available locally
  cups.service                   loaded active running CUPS Scheduler
  dbus.service                   loaded active running D-Bus System Message Bus
  fwupd.service                  loaded active running Firmware update daemon
  gdm.service                    loaded active running GNOME Display Manager
  ModemManager.service           loaded active running Modem Manager
  networkd-dispatcher.service    loaded active running Dispatcher daemon for systemd-networkd
  NetworkManager.service         loaded active running Network Manager
  polkit.service                 loaded active running Authorization Manager
```
