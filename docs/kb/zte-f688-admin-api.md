# ZTE F688 (GPON ONT) admin API — 192.168.2.1

How to script the home router's web admin without a browser. Verified live
2026-11-27 from tony-omen (the router is only reachable on the LAN — run from
a host on 192.168.2.0/24, e.g. `ssh tony-omen`).

Router: ZTE F688 ONT, admin UI `http://192.168.2.1/`. Despite env var names,
`~/.config/secrets/asus-router.env` (`ASUS_ROUTER_USER`/`ASUS_ROUTER_PASS`)
holds the working credentials (`admin`).

## Login flow

1. `GET /` → HTML login page (entity-encoded; HTML-unescape before parsing).
   Extract hidden input `id="_sessionTOKEN" value="<digits>"`. Keep cookies
   (SID).
2. `GET /?_type=loginData&_tag=login_token` → body like
   `<ajax_response_xml_root>72893147</ajax_response_xml_root>`; the token is
   the element text.
3. `POST /?_type=loginData&_tag=login_entry` form fields:
   - `action=login`
   - `Password` = lowercase hex `sha256(password + tokenText)`
   - `Username` = admin user
   - `_sessionTOKEN` = the hidden-input value from step 1

   Response: `{"sess_token":"<16 digits>","login_need_refresh":true}` + SID
   cookie. `login_need_refresh` just means "reload the page" — session is live.

## Loading pages and data

- Menu tree is embedded in the authenticated `GET /` as `menuTreeJSON`
  (id/name/area → `*.lp` / `*_lua.lua` files).
- Page HTML: `GET /?_type=menuView&_tag=<pageId>` e.g. `lanMgrIpv4`
  (Local Network → LAN → IPv4). Response embeds
  `_sessionTmpToken = "\x..\x.."` — hex-escaped ASCII; decode to a 16-digit
  token. **This token is required on every subsequent data call.**
- Section data: `GET /?_type=menuData&_tag=<name>_lua.lua&_sessionTOKEN=<tmpToken>`
  with headers `X-Requested-With: XMLHttpRequest` and `Referer: /`.
  - NOTE the tag needs the literal `.lua` suffix and the `_lua` stem:
    form-action says `..._DHCPStaticRule_lua.lua`; dropping `.lua` or the
    `_lua` stem returns `SessionTimeout`.
  - Returns `<ajax_response_xml_root>` with `<OBJ_...><Instance>` blocks;
    each Instance is ParaName/ParaValue pairs.

## Writes (apply changes)

POSTs go to the same `form-action` URL (menuData endpoint) as
`application/x-www-form-urlencoded` with:

- body = form fields + `&_sessionTOKEN=<tmpToken>`
- header `Check:` = base64 RSA-PKCS1v15 encryption of
  `sha256hex(bodyString)` using the pubkey embedded in the page JS
  (`asyEncode()` in the login page; JSEncrypt default = PKCS1 v1.5).
  Python `cryptography` can reproduce it (pubkey is in the page source).

## LAN IPv4 / DHCP binding data (verified 2026-11-27)

- DHCP server: `Localnet_LanMgrIpv4_DHCPBasicCfg_lua.lua` — pool
  192.168.2.65–192.168.2.99, lease 86400s, gw/DNS 192.168.2.1.
- Static bindings: `Localnet_LanMgrIpv4_DHCPStaticRule_lua.lua` —
  `OBJ_DHCPBIND_ID/Instance` rows: `_InstID` (DEV.V4DHCP.Server.Pool1.BindN),
  `Name`, `IPAddr`, `MACAddr`.
- Current leases: `Localnet_LanMgrIpv4_DHCPHostInfo_lua.lua` —
  `OBJ_...HI*` rows with PhyPortName (LANx/SSSID), IPAddr, MACAddr,
  HostName, ExpiredTime (-1 = bound/static).

Gotchas: binding table caps at 10 entries; binding names must not share a
prefix with an existing name; InstIDs have gaps (Bind7 was deleted once).
