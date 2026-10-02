# Anna's Warden on the MacBook

This is the second side of "Is Anna OK?". Anna's Warden and app run on your MacBook (macOS, zsh, repo at `~/nvidia-claw`). They pair with **your** Warden on the server through the server's relay, which is reachable on the tailnet only.

Anna's Warden only **answers**. It builds no watchers, so no worry text leaves the Mac and nothing on the Mac needs a sandbox (see "What proves privacy on the Mac" below). Everything is in one script, `scripts/anna-setup.sh`.

## Before you start
- Tailscale is running on the Mac and logged in to the same tailnet as the server.
- The server publishes the relay on the tailnet (done on 2 Oct). Check it from the Mac; you should see `{"status":"ok"}`:

```
curl -s https://ubuntu-s-4vcpu-8gb-fra1.tail081ca8.ts.net/relay/v1/health
```

## 1. Set up (once, about 5 minutes)
```
cd ~/nvidia-claw
git pull
./scripts/anna-setup.sh
```
It installs whatever is missing (uv, pnpm 9.15.9, Node 22), the Python and app dependencies, and writes `~/.config/custody-anna/warden.env`. That file holds Anna's settings and a new device token, and is mode 600. It never prints the token.
- If it stops with "git is missing", run `xcode-select --install`, then run the script again.
- If it stops at "can't reach …/relay", Tailscale isn't connected.

## 2. Start Anna's Warden and app
```
./scripts/anna-setup.sh start
```
The browser opens `http://127.0.0.1:5173`. The device token is already on the clipboard: press **Cmd-V** in "Device token", then **Connect**. Keep this terminal open; **Ctrl-C** stops both the app and the Warden. If you need the token again, run this in a second terminal tab:

```
cd ~/nvidia-claw
./scripts/anna-setup.sh token
```

## 3. Pair your phone with Anna's Mac
1. **Phone (you):** People → Pair with someone → **Show a code**. "What do you call them?" → `Anna` → Show a code.
2. **Mac (Anna):** People → Pair with someone → **Enter their code**. "What do you call them?" → `Myron`. Type the code from the phone → **Pair**.
3. **Both screens now show an 8-digit number.** If they are the same, tap **It matches** on both. If not, tap **It doesn't match** and start again.

## 4. Anna says she's OK
**Mac:** People → **What others can ask about me** → under **Right now**, tap **I'm OK**. The card then reads "Normal day". It counts for 3 hours.

- **Why this step:** a fresh Mac has less than 3 days of activity history. Until Anna checks in, the honest answer is "Not enough to say".
- After 3 days, the Mac's own idle time (macOS `ioreg`) answers without a check-in.
- **I need help** overrides everything until Anna taps **I'm fine again**.

## 5. Ask
**Phone:** People → **Is Anna OK?**
- The answer and its privacy receipt ("Shared: 1 answer, … bytes, encrypted. Location: never.") come back in about a second.
- On the Mac, the question appears under **Who asked**.
- Asking again within 10 minutes is refused on purpose: no "check again" loop.

## 6. Show the proof (for the video)
With `start` still running, in a second terminal tab:

```
cd ~/nvidia-claw
./scripts/anna-setup.sh proof
```
It prints three things:
1. **Every TCP connection of Anna's Warden.** Expected: only the relay (`100.81.50.38:443`) and loopback.
2. What an allowed person would hear now.
3. Every question asked about Anna and what was answered.

The server side of the same exchange (the relay holding only ciphertext) is in `scripts/demo-evidence.sh` on the server.

## What proves privacy on the Mac (and what doesn't)
OpenShell runs Linux sandboxes, and **no OpenShell sandbox runs on this Mac**. That's not needed, because Anna's Warden runs no watcher code. The Mac side does **not** claim a jail. What the privacy rests on:
1. **A fixed vocabulary, enforced before encryption.** An answer is `level` + `reason` + `ts` from a fixed list. Anything else is rejected before it is encrypted (`warden/tests/test_reassurance_vocabulary.py`). There is no location field at all.
2. **End-to-end encryption.** The relay on the server stores ciphertext and key ids only (shown by `scripts/demo-evidence.sh`, and by `warden/tests/test_l2_end_to_end.py`).
3. **The process's own connections.** `proof` lists every TCP connection Anna's Warden has open.
- **What this doesn't prove:** this is a snapshot taken at that moment, not a firewall. On the server, the OpenShell egress log of a watcher *is* enforced. Here it is only observed.
- **One more honest limit:** the relay sees who talks to whom and when (key ids, times and sizes), never what (THREAT_MODEL A6).

## Stop, reset
```
./scripts/anna-setup.sh stop
```
To give Anna a brand-new identity (new keys, new token, no pairings), delete `~/.config/custody-anna` and `~/.local/share/custody-anna`, then run `./scripts/anna-setup.sh` again. On your phone, remove the old "Anna" first. Re-pairing with the same Warden is refused (`409`) until the old pairing is removed.
