"""
Encryption utilities for PII and sensitive data protection.
Provides field-level encryption for database columns.
"""

import base64
import os
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""
    pass


class FieldEncryption:
    """
    Field-level encryption for sensitive data.
    Uses Fernet (symmetric encryption) with key derivation.
    
    Usage:
        encryptor = FieldEncryption()
        encrypted = encryptor.encrypt("sensitive_string")
        decrypted = encryptor.decrypt(encrypted)
    """

    def __init__(self, key: str | None = None):
        """
        Initialize encryptor.
        
        Args:
            key: Encryption key (uses ENCRYPTION_KEY env var if not provided)
        """
        if key is None:
            key = os.getenv("ENCRYPTION_KEY")
            if not key:
                raise EncryptionError(
                    "ENCRYPTION_KEY environment variable not set. "
                    "Generate with: openssl rand -base64 32"
                )
        
        # Derive consistent key from master key
        self._key = self._derive_key(key)
        self._cipher = Fernet(self._key)

    @staticmethod
    def _derive_key(master_key: str) -> bytes:
        """
        Derive a Fernet-compatible key from a master key using PBKDF2.
        
        Args:
            master_key: The master encryption key
            
        Returns:
            Base64-encoded key suitable for Fernet
        """
        # Use a fixed salt for consistent key derivation
        # (same master key always produces same derived key)
        salt = b"narrative_merge_engine_v1"  # Fixed salt for deterministic derivation
        
        kdf = PBKDF2(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100_000,
            backend=default_backend(),
        )
        
        derived = kdf.derive(master_key.encode())
        return base64.urlsafe_b64encode(derived)

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a string.
        
        Args:
            plaintext: Data to encrypt
            
        Returns:
            Base64-encoded encrypted ciphertext (safe to store in DB)
            
        Raises:
            EncryptionError: If encryption fails
        """
        try:
            ciphertext = self._cipher.encrypt(plaintext.encode())
            # Return as base64 string for safe DB storage
            return base64.b64encode(ciphertext).decode()
        except Exception as e:
            raise EncryptionError(f"Encryption failed: {e}")

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a string.
        
        Args:
            ciphertext: Base64-encoded encrypted data
            
        Returns:
            Decrypted plaintext
            
        Raises:
            EncryptionError: If decryption fails
        """
        try:
            # Decode from base64 first
            encrypted = base64.b64decode(ciphertext.encode())
            plaintext = self._cipher.decrypt(encrypted)
            return plaintext.decode()
        except Exception as e:
            raise EncryptionError(f"Decryption failed: {e}")


class EncryptedStr:
    """
    SQLAlchemy TypeDecorator for encrypted string columns.
    Transparently encrypts/decrypts on storage/retrieval.
    
    Usage:
        raw_text: Mapped[str] = mapped_column(EncryptedStr)
    """

    def __init__(self):
        self._encryptor = FieldEncryption()

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        """Encrypt before storing in DB."""
        if value is None:
            return None
        return self._encryptor.encrypt(str(value))

    def process_result_value(self, value: Any, dialect: Any) -> str | None:
        """Decrypt after retrieval from DB."""
        if value is None:
            return None
        return self._encryptor.decrypt(value)


# Module-level convenience functions
_default_encryptor: FieldEncryption | None = None


def get_encryptor() -> FieldEncryption:
    """Get or initialize the default encryptor."""
    global _default_encryptor
    if _default_encryptor is None:
        _default_encryptor = FieldEncryption()
    return _default_encryptor


def encrypt(plaintext: str) -> str:
    """Convenience function to encrypt a string."""
    return get_encryptor().encrypt(plaintext)


def decrypt(ciphertext: str) -> str:
    """Convenience function to decrypt a string."""
    return get_encryptor().decrypt(ciphertext)
