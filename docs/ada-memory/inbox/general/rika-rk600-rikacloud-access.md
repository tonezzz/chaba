---
bank: general
key: general/rika-rk600-rikacloud-access
kind: note
last_verified: '2026-09-22'
scope: shared
source: voice
status: active
subject: Rika RK600 weather station work history
valid_from: '2026-09-22'
written_by: ada_remember
---
The michael-ha weather station is a Rika RK600-07B with an RK900 module, a Samkoon Android HMI at 192.168.31.148. From about Sept 16 the HMI lost its default route (gateway 192.168.31.1), so all cloud uploads failed with network-unreachable while local Modbus kept working. On Sept 22 the route was restored and uploads resumed at about one row per minute to the Rika cloud at 39.99.253.232:8899; the dashboard is reachable at 39.99.253.232 port 8000, agriculture chart. A watchdog service on tony-omen keeps the route and app alive. Still open: the rain sensor (element e5) has never reported nonzero, and upload registers 4-15 are all zero — the technician should do a bucket-tip test. Full runbook: docs/kb/rika-rk600-cloud-upload.md in the chaba repo.
