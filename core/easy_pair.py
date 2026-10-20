"""Experimental committed SAS pairing; see docs/spec-easy-pair-1.6.md before release."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time

from nacl.bindings import crypto_scalarmult_base

from . import pairing as p

PAIR_MODES = ["cpace_v3", "sas_v1"]
EASY_TYPES = frozenset(("easy_commit", "easy_reveal", "easy_proof", "easy_approve"))
DOMAIN = b"beamer-sas-v1/"
WINDOW_SECONDS = 60.0


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def window_ok(value):
    return isinstance(value, str) and len(value) == 32 and all(c in "0123456789abcdef" for c in value)


def eligible(machine):
    return (machine.get("pair_modes") == PAIR_MODES and window_ok(machine.get("nearby"))
            and p._id_text_ok(machine.get("id")) and p._name_ok(machine.get("name"))
            and p._platform_ok(machine.get("platform")) and p._port_ok(machine.get("port"))
            and machine.get("port") != 0)


class EasyPairWindow:
    def __init__(self, name, identity, platform, port, *, clock=time.monotonic, entropy=secrets.token_bytes):
        p._check_own(identity, platform, port)
        self.clock = clock
        self.deadline = clock() + WINDOW_SECONDS
        self.window = entropy(16).hex()
        self._scalar = entropy(32)
        self._nonce = entropy(32)
        self._own = {"nearby": self.window, "id": p._b64(identity), "name": name[:p.MAX_NAME_CHARS],
                     "platform": platform, "port": port, "pair_modes": PAIR_MODES.copy()}
        self.peer = None
        self.reveal = None
        self.remote_commit = None
        self.remote_reveal = None
        self._commit = None
        self._digest = None
        self._proof_key = self._approval_key = None
        self._state = "searching"
        self._sas = self.token = None
        self.local_approved = self.remote_approved = self.remote_proved = False

    @property
    def state(self):
        if self.clock() >= self.deadline:
            if self._state not in ("paired", "refused", "inactive", "not_saved", "expired"):
                self.cancel("expired")
            elif self._state == "paired":
                self._forget()
        return self._state

    @property
    def seconds_left(self):
        return max(0, int(self.deadline - self.clock() + 0.999))

    @property
    def active(self):
        return self.state in ("searching", "exchanging", "confirm", "waiting")

    @property
    def sas(self):
        return self._sas if self.state in ("confirm", "waiting") else None

    @property
    def attempt(self):
        return ":".join(sorted((self.window, self.peer["nearby"]))) if self.peer else None

    @property
    def ready(self):
        return self.active and self.remote_proved and self.local_approved and self.remote_approved

    def offer(self, address, reply_port):
        return {**self._own, "address": address, "reply_port": reply_port, "pairing": p.PAIRING_V3}

    def select(self, machine):
        if self.state != "searching" or not eligible(machine):
            raise p.PairingError(p.ERROR_VERSION if not eligible(machine) else p.ERROR_REFUSED)
        if machine["nearby"] == self.window or machine["id"] == self._own["id"]:
            raise p.PairingError(p.ERROR_REFUSED)
        self.peer = {key: machine[key] for key in (*self._own, "address", "reply_port")}
        self.reveal = {**self._own, "to": self.peer["nearby"], "share": p._b64(crypto_scalarmult_base(self._scalar)),
                       "nonce": p._b64(self._nonce)}
        self._commit = hashlib.sha512(DOMAIN + b"commit\0" + canonical(self.reveal)).digest()
        self._state = "exchanging"

    def _message(self, kind, **fields):
        return {"type": kind, "from": self.window, "to": self.peer["nearby"], **fields}

    def messages(self):
        state = self.state
        if self.peer is None or state in ("inactive", "refused", "expired", "not_saved") or self.clock() >= self.deadline:
            return []
        messages = [self._message("easy_commit", commit=p._b64(self._commit))]
        if self.remote_commit is not None:
            messages.append(self._message("easy_reveal", reveal=self.reveal))
        if self._digest is not None:
            messages.append(self._message("easy_proof", tag=p._b64(self._tag("proof", self.window))))
        if self.local_approved:
            messages.append(self._message("easy_approve", tag=p._b64(self._tag("approved", self.window))))
        return messages

    def _tag(self, label, sender):
        key = self._proof_key if label == "proof" else self._approval_key
        return hmac.new(key, DOMAIN + label.encode("ascii") + b"\0" + sender.encode("ascii") + self._digest,
                        hashlib.sha512).digest()

    def receive(self, message, address):
        if not self.active or self.peer is None or address != self.peer["address"]:
            return
        if message.get("from") != self.peer["nearby"] or message.get("to") != self.window:
            return
        kind = message.get("type")
        field = {"easy_commit": "commit", "easy_reveal": "reveal", "easy_proof": "tag", "easy_approve": "tag"}.get(kind)
        if field is None:
            return
        if set(message) - {"beamy"} != {"type", "from", "to", field}:
            self.cancel("refused")
            return
        try:
            if kind == "easy_commit":
                commit = p._unb64(message["commit"])
                if len(commit) != 64 or (self.remote_commit is not None and not hmac.compare_digest(commit, self.remote_commit)):
                    raise p.PairingError(p.ERROR_REFUSED)
                self.remote_commit = commit
            elif kind == "easy_reveal":
                if self.remote_commit is None:
                    return
                reveal = message["reveal"]
                if not isinstance(reveal, dict) or set(reveal) != set(self.reveal):
                    raise p.PairingError(p.ERROR_REFUSED)
                if not hmac.compare_digest(hashlib.sha512(DOMAIN + b"commit\0" + canonical(reveal)).digest(), self.remote_commit):
                    raise p.PairingError(p.ERROR_REFUSED)
                if self.remote_reveal is not None:
                    if reveal != self.remote_reveal:
                        raise p.PairingError(p.ERROR_REFUSED)
                    return
                expected = {key: self.peer[key] for key in self._own}
                if any(reveal[key] != value or type(reveal[key]) is not type(value) for key, value in expected.items()) or reveal["to"] != self.window:
                    raise p.PairingError(p.ERROR_REFUSED)
                share, nonce = p._unb64(reveal["share"]), p._unb64(reveal["nonce"])
                if len(share) != 32 or len(nonce) != 32 or not p._machine_id_ok(p._unb64(reveal["id"])):
                    raise p.PairingError(p.ERROR_REFUSED)
                shared = p._x25519(self._scalar, share)
                transcript = sorted((self.reveal, reveal), key=lambda item: item["nearby"])
                self._digest = hashlib.sha512(DOMAIN + b"transcript\0" + canonical(transcript)).digest()
                key = hmac.new(self._digest, shared, hashlib.sha512).digest()
                derive = lambda label: hmac.new(key, DOMAIN + label + b"\0" + self._digest, hashlib.sha512).digest()
                self.token = p._b64(derive(b"token")[:32])
                self._proof_key, self._approval_key = derive(b"proof-key"), derive(b"approval-key")
                sas_key = derive(b"sas-key")
                counter = 0
                while True:
                    value = int.from_bytes(hmac.new(sas_key, DOMAIN + b"digits\0" + counter.to_bytes(4, "big"), hashlib.sha512).digest()[:4], "big")
                    if value < 4294000000:
                        self._sas = f"{value % 1000000:06d}"
                        break
                    counter += 1
                self.remote_reveal = reveal.copy()
            elif self._digest is not None:
                tag = p._unb64(message["tag"])
                label = "proof" if kind == "easy_proof" else "approved"
                if not hmac.compare_digest(tag, self._tag(label, self.peer["nearby"])):
                    raise p.PairingError(p.ERROR_REFUSED)
                if kind == "easy_proof":
                    self.remote_proved = True
                    self._state = "waiting" if self.local_approved else "confirm"
                elif self.remote_proved:
                    self.remote_approved = True
        except (p.PairingError, ValueError, TypeError, KeyError, UnicodeError):
            self.cancel("refused")

    def approve(self, sas, attempt):
        if self.state != "confirm" or sas != self.sas or attempt != self.attempt:
            self.cancel("refused")
            raise p.PairingError(p.ERROR_REFUSED)
        self.local_approved = True
        self._state = "waiting"

    def saved(self):
        # Authorisation was checked before store began. A disk write crossing the
        # deadline must still report the entry it actually saved.
        if self._state != "waiting" or not (self.remote_proved and self.local_approved and self.remote_approved):
            raise p.PairingError(p.ERROR_REFUSED)
        self._state = "paired"
        self._scalar = self._nonce = None

    def _forget(self):
        self._scalar = self._nonce = self._proof_key = self._approval_key = self.token = self._sas = None

    def cancel(self, state="inactive"):
        self._state = state
        self._forget()
