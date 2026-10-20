# Neptune Apex local API

The requests these shortcuts send, worked out by reading the Apex's own web
dashboard and checked against a real controller (type AC5L, AOS 5.16L). Neptune
Systems doesn't publish this API, so a firmware update can change it.

## The dashboard

The Apex serves its local dashboard at `http://<apex>/` over plain HTTP; it has no
HTTPS listener. The dashboard is a single Backbone.js app, `/main.js`, which the
Apex stores pre-compressed and only serves to clients that send
`Accept-Encoding: gzip` (other clients get a 404). Every request below is one that
app makes.

## Log in

```http
POST /rest/login
Content-Type: application/json

{"login": "admin", "password": "…", "remember_me": false}
```

- **Success:** `200` with `{"connect.sid": "<session id>"}`. The same id is also set
  as a `connect.sid` cookie. On the controller tested it was 24 letters and digits.
- **Wrong username or password:** `401` with an HTML error page.
- Send the session on later requests as `Cookie: connect.sid=<session id>`.
- There's no logout request; the dashboard's Sign Out only clears its own state.
- The dashboard trims spaces from the username and password before sending them.

## Start a feed cycle

```http
PUT /rest/status/feed/<id>
Cookie: connect.sid=<session id>
Content-Type: application/json

{"name": <id>, "active": 1}
```

| `id` | Feed cycle |
|---|---|
| `1`-`4` | Feed A-D |
| `0` | Cancel |

- The reply echoes the body with `"errorCode": 0` and `"errorMessage": ""` added.
- The new state shows up in the status (below) within a second or two.
- `name` and `active` are JSON numbers, as the dashboard sends them.

Where this comes from in `main.js`:

- The feed tile's buttons are `[CANCEL, A, B, C, D]`. Clicking one saves
  `{name: <index>, active: 1}`; CANCEL saves `{name: 0}`.
- The feed model is `{urlRoot: compositeURL, node: "feed", idAttribute: "name"}`.
  `compositeURL` is the parent model's URL plus `/` plus `node`, so saving the model
  sends a PUT to `/rest/status/feed/<name>`.

### Cancelling (not yet tested)

The dashboard's CANCEL changes only `name`, so it sends `{"name": 0, "active": <the
current countdown>}` to `/rest/status/feed/0`. For comparison, the request
[apex-ha](https://github.com/itchannel/apex-ha) uses,
`{"active": 92, "errorCode": 0, "errorMessage": "", "name": 0}`, did stop the feed,
but the status then reported `name` 256 until the original feed timer ran out, then 0.

## Read the status

```http
GET /cgi-bin/status.json
```

Needs no login on the controller tested, and comes with `Cache-Control: no-cache`.
Everything is under `istat`. Its `feed` is:

- `{"name": 0, "active": 0}` when no feed is running
- `{"name": <1-4>, "active": <seconds left>}` during a feed cycle

Other `istat` fields include `software` (firmware version), `type` (controller
type), `inputs` (probe readings), and `outputs`. The first item of each output's
`status` array is its state: `AON`/`AOF` (auto, currently on or off), `ON`/`OFF`
(manually set), or `TBL` (following a profile).

`GET /rest/status` (with the session cookie) returns the dashboard's fuller status,
with `feed` at the top level.

## Headers you can leave out

On writes, the dashboard also sends a `csrf-token` header, plus `accept-version: 1`
on every request. The CSRF code is shared with Apex Fusion's web app; the Apex
dashboard has no token, so the header goes out as the literal text `undefined`.
Requests without either header work.

## Not used yet (not tested)

- **Set an output:** apex-ha sends `PUT /rest/status/outputs/<did>` with
  `{"did": "<did>", "status": ["<ON|OFF|AUTO>", "", "OK", ""], "type": "outlet"}`.
  The dashboard's output tiles likewise save a new first `status` item and keep the rest.
- **Configuration and logs:** the dashboard reads `/rest/config` and the logs at
  `/rest/ilog`, `/rest/dlog`, `/rest/olog`, and `/rest/tlog`.
