# Minimal live API test plan (to be executed by the user with own credentials)

[Deutsch](api-testplan.md)

Purpose: Prove whether the Tuya OpenAPI can list, read and control devices without a Smart Life user account concept. **Never copy secrets or tokens into this repository or the chat.** Mask responses before sharing.

As of 2026-11-27. All paths use placeholders.

## Preparation

Choose the region matching the project:

| Region | Base URL |
|---|---|
| CN | `https://openapi.tuyacn.com` |
| US (West) | `https://openapi.tuyaus.com` |
| US (East) | `https://openapi-ueaz.tuyaus.com` |
| EU (Central) | `https://openapi.tuyaeu.com` |
| EU (West) | `https://openapi-weaz.tuyaeu.com` |
| IN | `https://openapi.tuyain.com` |
| SG | `https://openapi-sg.iotbing.com` |

Signature (per request):

```text
stringToSign = METHOD + "\n" + SHA256(body_hex) + "\n" + "" + "\n" + path?query

Token call:
sign = UPPER(HMAC_SHA256(secret, client_id + t + nonce + stringToSign))

Business call:
sign = UPPER(HMAC_SHA256(secret, client_id + access_token + t + nonce + stringToSign))
```

- Empty body hash: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- Sort query parameters alphabetically.
- `t` = 13-digit Unix millisecond timestamp.
- `nonce` = random UUID, identical in header and signature.
- Headers: `client_id`, `sign`, `sign_method: HMAC-SHA256`, `t`, `nonce`, plus `access_token` for business calls.
- For POST: `Content-Type: application/json`.

Recommendation: let `tuya-connector-python` compute the signature instead of implementing it yourself. The test still remains a real OpenAPI call with Access ID/Secret.

## T0 – Project token

```http
GET {BASE}/v1.0/token?grant_type=1
client_id: <ACCESS_ID>
sign_method: HMAC-SHA256
t: <MS>
nonce: <UUID>
sign: <SIGN>
```

**Expected:** `access_token`, `refresh_token`, `expire_time`, `uid` (with/without `result` wrapper depending on parser).

**Proof:** Access ID/Secret, region, timestamp and signature are correct. Without success everything else is worthless.

## T1 – List devices in the project data area

```http
GET {BASE}/v1.3/iot-03/devices?page_size=20
access_token: <PROJECT_TOKEN>
...signature headers...
```

Alternative for smart-home projects:

```http
GET {BASE}/v1.0/devices?page_no=1&page_size=20
```

**Expected:** `result.list[]` or `result.devices[]` with `id`, `uuid`, `name`, `product_id`, `category`, `online`, `owner_id`, `local_key`, `has_more`, `last_row_key`, `total`.

**Proof:** The project token sees devices **without app user login**. Empty list: wrong region, no devices in project or devices only in app account.

## T2 – Read device status

```http
GET {BASE}/v1.0/iot-03/devices/{DEVICE_ID}/status
access_token: <PROJECT_TOKEN>
```

**Expected:** `result[]` with `code` and `value`, e.g. `{"code":"switch_led","value":true}`.

**Proof:** Read access to current state.

## T3 – DPS/function vocabulary

```http
GET {BASE}/v1.0/iot-03/devices/{DEVICE_ID}/specification
GET {BASE}/v1.0/iot-03/devices/{DEVICE_ID}/functions
```

**Expected:** `result.category`, `result.functions[] {code,type,values}`, `result.status[] {code,type,values}`.

**Proof:** Valid DPS codes for this device. Without this step no command may be guessed.

## T4 – Control with pure project token (decisive)

Only with an **own, safe device** and a code known from T3:

```http
POST {BASE}/v1.0/iot-03/devices/{DEVICE_ID}/commands
Content-Type: application/json
access_token: <PROJECT_TOKEN>

{"commands":[{"code":"<SAFE_CODE>","value":<SAFE_VALUE>}]}
```

**Expected:** `result: true`, `success: true`. Then repeat T2 and check the change.

**Proof:** Final answer whether project-only can not only read but **control**. A permission error here is the decisive negative finding.

## T5 – Make linked app devices visible

```http
GET {BASE}/v1.0/iot-01/associated-users/devices?size=20
access_token: <PROJECT_TOKEN>
```

**Expected:** `result.devices[]`, `has_more`, `last_row_key`, `total`; per device `id`, `uid`, `owner_id`, `local_key`, `status`, `product_id`.

**Proof:** "Link App Account" has placed devices in the project data area. Compare `uid` with the app account UID shown in the console.

## T6 – Control permission for linked devices (disputed)

```http
POST {BASE}/v1.0/iot-03/devices/{LINKED_DEVICE_ID}/commands
Content-Type: application/json
access_token: <PROJECT_TOKEN>

{"commands":[{"code":"<SAFE_CODE>","value":<SAFE_VALUE>}]}
```

**Possible results:**

- `result: true` → control with project token allowed in this project/permission package.
- Error, typically `1106 illegal permission` → matches the official statement "view device status only".

**Proof:** The disputed core question for the concrete configuration. More important than any general documentation statement.

## T7 – Check user context (only if T6 negative)

Variant A:

```http
POST {BASE}/v1.0/iot-01/associated-users/actions/authorized-login
Content-Type: application/json

{"username":"<APP_LOGIN>","password":"<APP_PASSWORD>","country_code":<CC>,"schema":"tuyaSmart"}
```

**Expected:** `result.access_token`, `result.refresh_token`, `result.uid`, `result.expire_time`.

Then repeat T6 with `access_token: <USER_TOKEN>`.

Variant B: Home Assistant-like QR user code flow via `tuya_sharing.LoginControl`.

**Proof:** If T6 fails with project token and succeeds with user token, it is finally clear: linking + app login required → the important rule would be violated for linked devices.

## T8 – Cleanly separate UID/home/asset

```http
GET {BASE}/v2.0/apps/{SCHEMA}/users?page_no=1&page_size=50&start_time=<10_DIGIT>&end_time=<10_DIGIT>
GET {BASE}/v1.0/users/{UID}/homes
GET {BASE}/v1.0/homes/{HOME_ID}/devices
```

**Proof:** Whether `open_uid`/app account UID is the same identity as in home/associated-user APIs. Prevents confusion of `uid`, `home_id`, `owner_id`, `asset_id`.

## T9 – IoT Core thing shadow (charger data)

```http
GET {BASE}/v2.0/cloud/thing/{DEVICE_ID}/shadow/properties
access_token: <PROJECT_TOKEN>
```

**Expectation:** `success=true`, `result.properties[]` with `code`, `value`, `dp_id`, `time`. In this case 23 entries, including `x_work_state`, `x_work_st_debug`, `x_metrics`, `x_charger_info`, `x_charge_current`.

**Proof:** The thing shadow returns values even when `v1.0/devices/{id}/status`, `/functions` and `/specifications` are empty or unsupported. Without IoT Core authorization: `28841105`. Report only the result structure and count; do not publish values linked to the device.

## T10 – Stream allocation (live view)

```http
POST {BASE}/v1.0/devices/{DEVICE_ID}/stream/actions/allocate
Content-Type: application/json
access_token: <PROJECT_TOKEN>

{"type":"hls"}
```

**Expectation:** `success=true`, `result.url` containing `.m3u8` and a signature query. `{"type":"rtsp"}` also returns `success=true`. `webrtc-configs` reports `device not supports`.

**Proof:** Live view with the project token alone. The URL is short-lived and must **never** appear in the repo, chat, logs, diagnostics, state or attributes. The test only reports success and URL shape.

## Evaluation

| Tests | Result | Consequence |
|---|---|---|
| T0–T4 green | Project-only proven for own devices | Implementation may start (scope: own project devices) |
| T0–T3, T5 green, T4/T6 red | Read-only without app account | No control → goal not achievable; architecture must check user-token layer or another device model |
| T1 empty, T5 green | Devices only in app account | No devices without app account → goal not achievable |
| T6 red, T7 green | App login mandatory for control | Important rule violated; integration would not be "without Smart Life login" |
| T0 red | Credentials/region/signature wrong | General error, no feasibility verdict |
| T9 green | Charger data readable without app account | Shadow sensors may be built |
| T10 green | HLS live view with project token | Camera platform may be built |

**Important:** For each test report only the masked result (`success`, `errno`, field names, record count) – never tokens, secrets, `local_key` values or personal device names.
