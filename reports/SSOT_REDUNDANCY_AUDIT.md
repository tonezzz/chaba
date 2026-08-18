# SSOT Redundancy Audit

Generated during Phase 3 of the SSOT File Optimization Plan.

## Cross-file duplicate labels

- **Registry** appears in: apps/ssot.apps.raceman.yml, apps/ssot.apps.test-carplay.yml, apps/ssot.apps.test-pwa.yml, apps/ssot.apps.wind.yml, apps/ssot.apps.yomi.yml, ssot.libs.yml
- **Location** appears in: apps/ssot.apps.helm.yml, apps/ssot.apps.raceman.yml, apps/ssot.apps.test-carplay.yml, apps/ssot.apps.test-pwa.yml, apps/ssot.apps.yomi.yml
- **tony-omen** appears in: infrastructure/ssot.hardware.yml, ssot.mysystem.home.yml, ssot.mysystem.mobile.yml
- **Chaba-h3 Preview** appears in: ssot.mysystem.home.yml, ssot.mysystem.mobile.yml
- **index.html** appears in: apps/ssot.apps.map3d.yml, apps/ssot.apps.raceman.yml, apps/ssot.apps.test-carplay.yml, apps/ssot.apps.test-pwa.yml
- **URLs** appears in: apps/ssot.apps.helm.yml, apps/ssot.apps.raceman.yml, apps/ssot.apps.test-carplay.yml, apps/ssot.apps.yomi.yml
- **Profile Switching** appears in: ssot.mysystem.home.yml, ssot.mysystem.mobile.yml
- **Apps Server** appears in: ssot.mysystem.home.yml, ssot.mysystem.mobile.yml
- **PostgreSQL** appears in: apps/ssot.apps.yomi.yml, ssot.mysystem.home.yml, ssot.mysystem.mobile.yml
- **tony-dell** appears in: infrastructure/ssot.hardware.yml, ssot.mysystem.home.yml
- **Branch** appears in: apps/ssot.apps.test-carplay.yml, apps/ssot.apps.test-pwa.yml, apps/ssot.apps.yomi.yml
- **Context improvement and optimization** appears in: ssot.focus.current.yml, ssot.focus.yml
- **Migrate helm to tony-dell podman** appears in: ssot.focus.current.yml, ssot.focus.yml
- **playlive-server.py** appears in: apps/ssot.apps.aihub.yml, ssot.diagrams.yml
- **Chrome CDP** appears in: apps/ssot.apps.aihub.yml, ssot.diagrams.yml
- **redis** appears in: infrastructure/ssot.containerization.yml, ssot.diagrams.yml
- **Redis** appears in: ssot.diagrams.yml, ssot.mysystem.macbook.yml
- **This SSOT** appears in: apps/ssot.apps.aihub.yml, ssot.diagrams.yml
- **Goal** appears in: apps/ssot.apps.aihub.yml, ssot.file-optimization.yml
- **Manual override** appears in: apps/ssot.apps.track4.yml, ssot.file-optimization.yml
- **Network Type** appears in: ssot.mysystem.home.yml, ssot.mysystem.mobile.yml
- **Access Method** appears in: ssot.mysystem.home.yml, ssot.mysystem.mobile.yml
- **SSH Config** appears in: ssot.mysystem.macbook.yml, ssot.mysystem.mobile.yml
- **llama-router** appears in: ssot.mysystem.home.yml, ssot.mysystem.mobile.yml
- **postgres** appears in: ssot.mysystem.home.yml, ssot.mysystem.mobile.yml
- **cams** appears in: ssot.mysystem.home.yml, ssot.mysystem.mobile.yml
- **track4** appears in: ssot.mysystem.home.yml, ssot.mysystem.mobile.yml
- **Apps (tony-omen)** appears in: ssot.mysystem.home.yml, ssot.mysystem.mobile.yml
- **Llama Router API** appears in: ssot.mysystem.home.yml, ssot.mysystem.mobile.yml
- **SSH Access** appears in: ssot.mysystem.macbook.yml, ssot.mysystem.mobile.yml
- **Switch to Mobile Profile** appears in: ssot.mysystem.home.yml, ssot.mysystem.mobile.yml
- **tony-omen GPU** appears in: infrastructure/ssot.hardware.yml, ssot.mysystem.home.yml
- **yomi-api** appears in: infrastructure/ssot.containerization.yml, ssot.mysystem.home.yml
- **GPU Queue** appears in: apps/ssot.apps.yomi.yml, ssot.mysystem.home.yml
- **Node.js** appears in: ssot.mysystem.macbook-appdev.yml, ssot.mysystem.macbook.yml
- **Homebrew** appears in: ssot.mysystem.macbook-appdev.yml, ssot.mysystem.macbook.yml
- **FileVault** appears in: ssot.mysystem.macbook-appdev.yml, ssot.mysystem.macbook.yml
- **Firewall** appears in: ssot.mysystem.macbook-appdev.yml, ssot.mysystem.macbook.yml
- **Rules** appears in: ssot.file-control.yml, ssot.terminology.yml
- **SSOT** appears in: apps/ssot.apps.wind.yml, ssot.terminology.yml
- **Weaviate** appears in: apps/ssot.apps.yomi.yml, ssot.docs.yml
- **Scope** appears in: apps/ssot.apps.aihub.yml, ssot.file-control.yml
- **Pre-commit** appears in: ssot.file-control.yml, ssot.libs.yml
- **Service Failures Detected** appears in: ssot.focus.yml, ssot.improvements.yml
- **Security Vulnerabilities Found** appears in: ssot.focus.yml, ssot.improvements.yml
- **Source** appears in: apps/ssot.apps.wind.yml, ssot.libs.yml
- **Git Version Control** appears in: infrastructure/ssot.disaster-recovery.yml, ssot.documentation-infrastructure.yml
- **Documentation Recovery** appears in: infrastructure/ssot.disaster-recovery.yml, ssot.documentation-infrastructure.yml
- **main.js** appears in: apps/ssot.apps.map3d.yml, apps/ssot.apps.test-carplay.yml
- **Unit tests** appears in: apps/ssot.apps.raceman.yml, apps/ssot.apps.track4.yml
- **3D Gaussian Splat** appears in: apps/ssot.apps.raceman.yml, apps/ssot.apps.track4.yml
- **Performance** appears in: apps/ssot.apps.raceman.yml, apps/ssot.apps.track4.yml
- **Capture** appears in: apps/ssot.apps.aihub.yml, apps/ssot.apps.playlive.yml
- **Start daemon** appears in: apps/ssot.apps.aihub.yml, apps/ssot.apps.playlive.yml
- **Navigate** appears in: apps/ssot.apps.aihub.yml, apps/ssot.apps.playlive.yml
- **Purpose** appears in: apps/ssot.apps.docs.yml, apps/ssot.apps.track4.yml
- **playlived** appears in: apps/ssot.apps.aihub.yml, infrastructure/ssot.tony-dell-monitoring.yml

## Notes

- Same labels in `ssot.mysystem.home.yml` and `ssot.mysystem.mobile.yml` are usually intentional per-host variants.
- Duplicates within the same file are not listed; those are handled by the intra-file duplicate check.
- Next step: review top candidates and decide merge, cross-reference, or rename.
