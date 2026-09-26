#!/usr/bin/env python3
"""Gera o hash de senha p/ ADMIN_PASSWORD_HASH (.env)."""
import getpass
from werkzeug.security import generate_password_hash
pw = getpass.getpass("Senha: ")
if len(pw) < 8:
    raise SystemExit("Use pelo menos 8 caracteres.")
if pw != getpass.getpass("Confirme: "):
    raise SystemExit("Senhas não conferem.")
print("\nADMIN_PASSWORD_HASH=" + generate_password_hash(pw))
