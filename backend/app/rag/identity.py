"""Stable source and embedding-space identities; never include credentials."""
from copy import deepcopy
import hashlib
import json
import os


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def document_key(doc):
    return f"{doc['id']}@{doc['version']}"


def source_version_hash(doc):
    value = deepcopy(doc)
    for field in ('active', 'is_current'):
        value.pop(field, None)
    return digest(canonical(value))


def embedding_input_hash(text):
    return digest(text)


def embedding_profile(provider, *, space_revision=None):
    endpoint = getattr(provider, 'base_url', 'local://hash').rstrip('/')
    return {'provider': provider.kind, 'model': provider.model, 'dimensions': provider.dimensions,
            'endpointDigest': digest(endpoint), 'adapterVersion': getattr(provider, 'adapter_version', 'a04-v1'),
            'spaceRevision': space_revision or os.environ.get('DORA_RAG_EMBEDDING_SPACE_REVISION', 'a06-v1'),
            'inputTemplate': 'title-newline-chunk-v1', 'normalizer': 'strip-empty-lines-v1',
            'chunker': 'paragraph-500-overlap-60-v1'}


def profile_hash(profile):
    return digest(canonical(profile))
