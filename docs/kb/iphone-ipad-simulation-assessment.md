---
title: iPhone/iPad simulation assessment — testing Apple devices on Linux
description: Complete survey of options for simulating, emulating, and testing iPhone/iPad behavior on Linux hosts — Playwright WebKit device profiles, QEMU iOS research projects, macOS-in-container running the real Xcode Simulator, Corellium/cloud device farms, and libimobiledevice real-device debugging — with a recommended stack for our PWA/GEV testing needs
tags: [ios, ipad, iphone, simulation, testing, playwright, webkit, qemu, pwa, safari]
created: 2026-09-27
updated: 2026-09-27
category: architecture
related: [docs/kb/gesture-ui-options.md]
search_keywords:
  [
    iphone emulator linux,
    ipad simulation,
    run ios on linux,
    playwright webkit iphone,
    qemu iphone emulation,
    xcode simulator linux,
    corellium virtual ios,
    ios safari testing,
    pwa testing ipad,
    ios-webkit-debug-proxy,
    libimobiledevice linux,
  ]
---

# iPhone/iPad Simulation Assessment

How to test iPhone/iPad behavior from a Linux host (tony-omen, tony-dell,
idc01), and how faithful each option is. Researched 2026-09-27.

## Verdict up front

There is **no free, legal, full-fidelity iPhone/iPad emulator for Linux**.
But ~85% of what we actually test (PWA pages, Safari rendering, touch
viewport, WebKit quirks) is coverable by **Playwright's WebKit engine with
Apple device profiles** — the single highest-value option. Real-device
debugging over USB (`ios-webkit-debug-proxy`) covers most of the rest.
A real iOS *Simulator* can be reached two ways: **macOS inside a
Docker/QEMU container** (works, heavy, EULA-gray) or **Corellium**
(commercial, real iOS on ARM cloud, ~$3/device-hour).

## The five meanings of "simulate"

| Level | What it is | Fidelity | Best tool |
|---|---|---|---|
| 1. Look-alike | UA + viewport + touch events | ~40% | Chrome DevTools, Playwright `devices` |
| 2. Real engine | WebKit rendering/JS engine on Linux | ~70% | Playwright `webkit`, WebKitGTK |
| 3. Real Safari | Apple's actual browser, but virtual machine | ~90% | Xcode Simulator in macOS VM |
| 4. Real iOS | Full OS w/ SpringBoard, virtualized | ~95% | Corellium, QEMU research builds |
| 5. Real device | Physical iPad/iPhone | 100% | libimobiledevice + ios-webkit-debug-proxy |

The trap: "iOS emulators" advertised online (iPadian etc.) are level-1 at
best — themed shells that run nothing real. Ignore them.

## Options

### A. Playwright WebKit + Apple device profiles — RECOMMENDED BASELINE

`npx playwright install webkit` ships a real WebKit build (WPE/WebKitGTK)
that runs natively on Linux. Device descriptors exist for iPhone 12/13/14
Pro and iPad Pro 11/13 — they set UA, viewport, `devicePixelRatio`,
`isMobile`, and `hasTouch`:

```js
{ name: "Mobile Safari", use: { ...devices["iPhone 13"] } }
{ name: "iPad",          use: { ...devices["iPad Pro 11"] } }
```

**Covers**: WebKit CSS/JS/layout bugs, touch events, `pointer: coarse`,
viewport meta behavior, Service Workers, IndexedDB (can be disabled to
repro iOS private-mode failures), screenshot diffing. All iOS browsers
are WebKit under the hood, so engine-level bugs reproduce.

**Does NOT cover** (needs level ≥3):
- iOS WebContent jetsam memory cap (~1.5–2 GB) — desktop WebKit has GBs
- Collapsing Safari address bar shifting `innerHeight`/`visualViewport`
- On-screen keyboard viewport resize
- **Standalone home-screen PWA behavior** — the mic restriction we hit
  on the GEV page lives here (Safari ≠ `apple-mobile-web-app-capable`
  standalone WKWebView)
- iOS Web Push, `Wake Lock`, real Safari version pinning

**Linux caveat**: headless WPE is ~4–5× slower than on macOS
(microsoft/playwright#34119). Workaround: run **headed under Xvfb**
(`headless: false` + `xvfb-run`) — confirmed to restore speed.
tony-omen already runs Xvfb on `:99`; the display stack exists.

Fits our stack: a `webkit-qa.mjs`-style harness against
`https://tony-dell.taila0626a.ts.net/apps/{gev,vcast,pwa}` can be a
scenario/smoke target — cheap, scripted, repeatable.

### B. Chrome DevTools / Firefox RDM device mode

UA + viewport + touch emulation on a Chromium/Firefox engine. Fine for
layout sanity, wrong engine for any real iOS bug. Use only as a quick
"does it fit the screen" check.

### C. QEMU-based iOS emulation — research-grade only

| Project | Target | State |
|---|---|---|
| `jprx/darwin-vm` | iPhone 12–17 (A14–A19), M1–M5 | Active 2025–26. Boots Darwin to **root shell in seconds** — NO screen, SpringBoard, GPU, Wi-Fi. Kernel/dyld debugging & CLI tools only. |
| `TrungNguyen1909/qemu-t8030` | iPhone 11 (A13) | Boots full iOS 14 w/ SpringBoard — real PoC, fragile, iOS 14-era, ~days of setup |
| `ChefKissInc/QEMUAppleSilicon` (+ `oleavr` fork) | iPhone 11, iOS 14b5 | Stale; superseded by darwin-vm |
| `devos50/qemu` | iPod Touch 1G/2G | Historical (iOS 1–3) |
| `corellium/projectsandcastle` | Linux ON iPhone hardware | Inverse direction; unmaintained |

Useful for security/kernel work. **Not usable for app or PWA testing** —
only t8030 reaches a GUI and it's years-old iOS on ancient hardware.

### D. macOS inside Docker/QEMU → real Xcode Simulator

`etasdemir/osx-container`, `Dockur/macos`, `sickcodes/Docker-OSX`,
`arindas/mac-on-linux-with-qemu` — macOS Ventura+ in a KVM-backed
container on Linux (`--device /dev/kvm`, X11 or VNC for display, ~60 GB
image, 8+ GB RAM). Inside it: Xcode → `simctl` → **the genuine iOS
Simulator** — same binary developers use on a Mac, current iOS, real
Safari, real standalone-PWA mode. `usbfluxd` can even redirect a real
iPhone's usbmuxd into the guest for device-deploy workflows.

**Reality check**: setup is hours, first-boot downloads several GB, and
the macOS EULA restricts it to Apple-branded hardware — technically
works, legally gray. If a true simulator is ever needed (testing the
standalone-PWA mic path, Wake Lock, exact iOS Safari version), this is
the only self-hosted route.

### E. Corellium — commercial virtual iPhones

`github.com/corellium` (38 repos; `usbfluxd` ★431). Full iOS on ARM
virtual machines in the cloud — any model + iOS version incl. betas,
full SpringBoard, optional jailbreak, USBFlux makes virtual devices
appear as local USB devices. Won the Apple copyright lawsuit (fair use,
2020–21); now Cellebrite. **Solo EDU: $3/device-hour**; trials are
reviewed. The only level-4 option that isn't a research toy — real iOS,
recent versions, browser-accessible from Linux. Worth a trial if we ever
need to verify behavior that only exists on real iOS.

### F. Real-device control + remote debugging from Linux — BEST REAL OPTION

`libimobiledevice` suite (active, cross-platform): `idevice_id`,
`idevicescreenshot`, `idevicesyslog`, app install/provisioning (with a
developer image), geolocation sim, WebKit remote-debug socket. On top:

- **`google/ios-webkit-debug-proxy`** — exposes real-device Safari over
  Chrome DevTools protocol. Plug the iPad into tony-omen, run
  `ios_webkit_debug_proxy`, get console/network/DOM of the *actual*
  page running in real Safari — level-5 fidelity for web bugs.
- `appium/appium-ios-device` — usbmuxd in Node; full XCUITest automation
  still wants macOS/Xcode, but device info/syslog/install works.

Requires `Settings → Safari → Advanced → Web Inspector = ON` on the
device and pairing trust once. Everything else is pure Linux.

### G. Cloud device farms

BrowserStack / Sauce Labs / LambdaTest — real devices + real Safari,
Appium-driven, per-minute billing, zero setup. Right tool for occasional
"does this actually work on iOS 18 Safari" validation without hardware.

## What can never be simulated

- The exact standalone-PWA WKWebView (mic/permissions differ from Safari)
- iOS version-specific Safari bugs (Playwright WebKit tracks ToT, not releases)
- True thermal/battery/low-memory pressure behavior
- Touch-ID/payments/keychain
- App-store app UI (only Safari/web is reachable without real iOS)

## Recommended stack for us

| Need | Tool | Cost | Effort |
|---|---|---|---|
| CI smoke: PWA/GEV/vcast on iPhone/iPad viewports w/ real WebKit | Playwright webkit, headed under Xvfb, `devices['iPhone 13']` / `['iPad Pro 11']` | free | hours |
| Debug a real reported iPad bug | ios-webkit-debug-proxy + real iPad on USB | free | ~30 min one-time setup |
| Standalone-PWA mode / exact Safari version, self-hosted | osx-container + Xcode sim (EULA-gray) | free | a day |
| Same, hosted & legal | Corellium trial / BrowserStack session | $3–5/hr | minutes |
| Full-OS iOS research | jprx/darwin-vm | free | hours |

**Suggested next step**: a `webkit-qa` scenario for ada-pi-pwa —
Playwright webkit + iPad Pro profile hitting the PWA on tony-dell —
would fold iOS regression coverage into the existing scenario/benchmark
harness (`scripts/scenario-benchmark.py`) for near-zero marginal cost.
