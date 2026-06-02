"""Encrypted transport for the admin <-> website socket protocol.

Hybrid scheme:
  * RSA-2048 (OAEP/SHA-256) is used once per connection to agree on a key.
  * AES-256-GCM encrypts every JSON message after the handshake.

Handshake (over the raw socket, newline-framed base64):
  1. server -> client : RSA public key (PEM)
  2. client -> server : AES session key, RSA-encrypted with that public key

After that both sides use SecureChannel.send_json / recv_json. Each frame on
the wire is base64(nonce[12] + ciphertext+tag) + "\n", so the existing
readline-based loops keep working unchanged.
"""

import base64
import json
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RSA_KEY_BITS = 2048
AES_KEY_BYTES = 32   # AES-256
NONCE_BYTES = 12     # GCM standard nonce size

_OAEP = padding.OAEP(
    mgf=padding.MGF1(algorithm=hashes.SHA256()),
    algorithm=hashes.SHA256(),
    label=None,
)


def generate_rsa_keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=RSA_KEY_BITS)


def _serialize_public_key(private_key):
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _write_line(f, data_bytes):
    f.write(base64.b64encode(data_bytes) + b"\n")
    f.flush()


def _read_line(f):
    line = f.readline()
    if not line:
        return None
    return base64.b64decode(line.strip())


class SecureChannel:
    """AES-256-GCM encrypted, newline-framed JSON channel over a socket file."""

    def __init__(self, sock_file, aes_key):
        self.f = sock_file
        self._aesgcm = AESGCM(aes_key)

    # ---------- handshake ----------
    @classmethod
    def server_handshake(cls, sock_file, private_key):
        # 1) hand the client our RSA public key
        _write_line(sock_file, _serialize_public_key(private_key))
        # 2) receive the RSA-encrypted AES session key
        enc_key = _read_line(sock_file)
        if enc_key is None:
            raise ConnectionError("Client closed during handshake.")
        aes_key = private_key.decrypt(enc_key, _OAEP)
        return cls(sock_file, aes_key)

    @classmethod
    def client_handshake(cls, sock_file):
        # 1) read the server's RSA public key
        pub_pem = _read_line(sock_file)
        if pub_pem is None:
            raise ConnectionError("Server closed during handshake.")
        public_key = serialization.load_pem_public_key(pub_pem)
        # 2) make an AES session key and send it back RSA-encrypted
        aes_key = os.urandom(AES_KEY_BYTES)
        _write_line(sock_file, public_key.encrypt(aes_key, _OAEP))
        return cls(sock_file, aes_key)

    # ---------- framed JSON ----------
    def send_json(self, obj):
        plaintext = json.dumps(obj).encode("utf-8")
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, None)
        _write_line(self.f, nonce + ciphertext)

    def recv_json(self):
        raw = _read_line(self.f)
        if raw is None:
            return None
        nonce, ciphertext = raw[:NONCE_BYTES], raw[NONCE_BYTES:]
        plaintext = self._aesgcm.decrypt(nonce, ciphertext, None)
        return json.loads(plaintext.decode("utf-8"))
