"""M0 smoke test: every core dependency imports, and PyTorch is the CPU-only build."""

import argon2
import faiss
import fastapi
import jwt
import sentence_transformers
import sqlalchemy
import torch
import yaml


def test_core_dependencies_import():
    for module in (argon2, faiss, fastapi, jwt, sentence_transformers, sqlalchemy, yaml):
        assert module is not None


def test_torch_is_cpu_only_build():
    assert "+cpu" in torch.__version__
