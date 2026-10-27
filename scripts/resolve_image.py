#!/usr/bin/env python3
"""Select one published CLI image for every job in a brick workflow run."""

import hashlib
import base64
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

REPOSITORY = 'ghcr.io/mass4org/turian-cli'
STABLE = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z')
SEMVER = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
                    r'(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?'
                    r'(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z')
PINNED = re.compile(re.escape(REPOSITORY) + r'(?:\:[A-Za-z0-9._-]+)?@sha256:[0-9a-f]{64}\Z')
ID = re.compile(r'[a-z0-9]+(?:[.-][a-z0-9]+)+\Z')
NOT_FOUND = object()


class SelectionError(Exception):
    """A named selection failure safe to print without response bodies or credentials."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PublicBlobRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != 'https':
            raise SelectionError('Image selection: registry blob redirect must use HTTPS.')
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header('Authorization')
        return redirected


def get_json(url, token='', missing=False, blob=False):
    headers = {'Accept': 'application/json', 'User-Agent': 'MASS4-brick-workflows'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.build_opener(PublicBlobRedirect if blob else NoRedirect).open(request, timeout=30) as response:
            return json.load(response), response.headers
    except urllib.error.HTTPError as error:
        if error.code == 404 and missing:
            return NOT_FOUND, {}
        raise SelectionError(f'GET {urllib.parse.urlsplit(url).path}: HTTP {error.code}; check credentials, scope and endpoint.') from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise SelectionError(f'GET {urllib.parse.urlsplit(url).path}: network failure or malformed JSON.') from None


def store_token(value):
    value = value.lstrip('\ufeff').strip()
    if value.startswith('{'):
        try:
            value = json.loads(value)['secret']
        except (ValueError, KeyError, TypeError):
            raise SelectionError('Store token: JSON export must contain a string secret.') from None
    if isinstance(value, str):
        value = value.strip()
    if not isinstance(value, str) or not re.fullmatch(r'mass4_[A-Za-z0-9_-]+', value):
        raise SelectionError('Store token: expected a raw mass4_ token or its JSON export.')
    return value


def receipt(store, token, package, version, variant):
    query = urllib.parse.urlencode({'variant': variant})
    url = f'{store.rstrip("/")}/api/v1/releases/{package}/{version}?{query}'
    value, _ = get_json(url, token, missing=True)
    if value is NOT_FOUND:
        return None
    if not isinstance(value, dict) or any(value.get(k) != v for k, v in
                                          [('packageId', package), ('version', version), ('variant', variant)]):
        raise SelectionError('Provenance: store receipt does not match the requested package, version and variant.')
    build = value.get('build')
    if not isinstance(build, dict) or not PINNED.fullmatch(build.get('image', '')) or not STABLE.fullmatch(build.get('turianVersion', '')):
        raise SelectionError('Provenance: existing release has no usable recorded CLI digest/version; refusing to guess a replacement.')
    return {**build, '_receipt': value}


def download_recorded(store, token, recorded, directory):
    """Retain exact immutable bytes when the store permits archive access."""
    identity = str(uuid.UUID(recorded['id']))
    filename = f'{recorded["packageId"]}-{recorded["version"]}--{recorded["variant"]}.brick'
    destination = directory / filename
    request = urllib.request.Request(f'{store.rstrip("/")}/api/v1/releases/{identity}/archive',
        headers={'Authorization': 'Bearer ' + token, 'User-Agent': 'MASS4-brick-workflows'})
    digest = hashlib.sha256()
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=60) as response, destination.open('wb') as output:
            while block := response.read(1024 * 1024):
                output.write(block)
                digest.update(block)
    except urllib.error.HTTPError as error:
        destination.unlink(missing_ok=True)
        if error.code == 404:
            print('::warning::Recorded archive is not downloadable; rebuild must match its recorded hash.')
            return {**recorded, 'file': filename, 'available': False}
        raise SelectionError(f'Provenance archive read returned HTTP {error.code}.') from None
    except (urllib.error.URLError, TimeoutError):
        destination.unlink(missing_ok=True)
        raise SelectionError('Provenance archive download failed before completion.') from None
    integrity = 'sha256-' + base64.b64encode(digest.digest()).decode()
    if integrity != recorded.get('integrity'):
        destination.unlink(missing_ok=True)
        raise SelectionError('Provenance archive bytes do not match the recorded integrity.')
    return {**recorded, 'file': filename, 'available': True}


class Registry:
    def __init__(self):
        body, _ = get_json('https://ghcr.io/token?service=ghcr.io&scope=repository:mass4org/turian-cli:pull')
        self.token = body['token']

    def highest(self):
        url = 'https://ghcr.io/v2/mass4org/turian-cli/tags/list?n=1000'
        versions = []
        visited = set()
        while url:
            if url in visited or not url.startswith('https://ghcr.io/v2/mass4org/turian-cli/tags/list'):
                raise SelectionError('Image selection: invalid registry pagination link.')
            visited.add(url)
            page, headers = get_json(url, self.token)
            if not isinstance(page.get('tags'), list):
                raise SelectionError('Image selection: malformed registry tag list.')
            versions.extend(v for v in page['tags'] if isinstance(v, str) and STABLE.fullmatch(v))
            link = headers.get('Link', '')
            match = re.search(r'<([^>]+)>;\s*rel="?next"?', link)
            url = urllib.parse.urljoin(url, match[1]) if match else ''
        if not versions:
            raise SelectionError('Image selection: registry has no stable semver CLI image tags.')
        return max(versions, key=lambda v: tuple(map(int, v.split('.'))))

    def manifest(self, reference):
        request = urllib.request.Request(f'https://ghcr.io/v2/mass4org/turian-cli/manifests/{reference}', headers={
            'Authorization': 'Bearer ' + self.token,
            'Accept': ', '.join(['application/vnd.oci.image.index.v1+json',
                                 'application/vnd.docker.distribution.manifest.list.v2+json',
                                 'application/vnd.oci.image.manifest.v1+json',
                                 'application/vnd.docker.distribution.manifest.v2+json']),
        })
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
                payload = response.read()
                digest = 'sha256:' + hashlib.sha256(payload).hexdigest()
                if response.headers.get('Docker-Content-Digest', digest) != digest:
                    raise SelectionError('Image selection: registry manifest digest does not match its bytes.')
                return digest, json.loads(payload)
        except (urllib.error.URLError, ValueError, TimeoutError):
            raise SelectionError('Image selection: requested CLI manifest is unavailable or malformed.') from None

    def resolve(self, reference, expected):
        digest, manifest = self.manifest(reference)
        canonical = digest
        if 'manifests' in manifest:
            platform = next((m for m in manifest['manifests']
                             if m.get('platform', {}).get('os') == 'linux'
                             and m.get('platform', {}).get('architecture') == 'amd64'), None)
            if platform is None:
                raise SelectionError('Image selection: CLI has no linux/amd64 image.')
            _, manifest = self.manifest(platform['digest'])
        config, _ = get_json(f'https://ghcr.io/v2/mass4org/turian-cli/blobs/{manifest["config"]["digest"]}', self.token, blob=True)
        label = config.get('config', {}).get('Labels', {}).get('org.opencontainers.image.version')
        if label != expected:
            raise SelectionError(f'Image selection: image version label {label!r} does not match selected {expected}.')
        return REPOSITORY + '@' + canonical


def select(requested='', package='', version='', token='', store='https://bricks.mass4.org', twin=True, registry=None,
           replay_directory=None):
    if requested and not STABLE.fullmatch(requested):
        raise SelectionError('turian-version must be an exact stable semver, such as major.minor.patch.')
    recorded = None
    records = []
    if token:
        if not ID.fullmatch(package) or not SEMVER.fullmatch(version):
            raise SelectionError('Provenance: invalid package id or tag version.')
        parsed = urllib.parse.urlsplit(store)
        if parsed.scheme not in ('https', 'http') or not parsed.netloc or parsed.username or parsed.password:
            raise SelectionError('Provenance: invalid store URL.')
        token = store_token(token)
        recorded = receipt(store, token, package, version, 'source')
        if recorded:
            records.append(recorded['_receipt'])
    registry = registry or Registry()
    if recorded:
        selected = recorded['turianVersion']
        image = registry.resolve(recorded['image'].split('@', 1)[1], selected)
        if image != REPOSITORY + '@' + recorded['image'].split('@', 1)[1]:
            raise SelectionError('Provenance: registry returned a different digest from the recorded build.')
        image = recorded['image']
        reason = 'store-record'
        if requested and requested != selected:
            print(f'::warning::turian-version {requested} is overridden by the recorded release build {selected}.')
    else:
        selected = requested or registry.highest()
        image = registry.resolve(selected, selected)
        reason = 'exact-override' if requested else 'highest-stable-semver'
    if token and twin:
        variant = 'turian' + '.'.join(selected.split('.')[:2])
        baked = receipt(store, token, package, version, variant)
        if baked and (baked['image'] != image or baked['turianVersion'] != selected):
            raise SelectionError('Provenance: source and twin record different build images; a single build cannot reproduce both.')
        if baked:
            records.append(baked['_receipt'])
    if replay_directory is not None and records:
        replay_directory.mkdir(parents=True, exist_ok=True)
        archives = [download_recorded(store, token, record, replay_directory) for record in records]
        (replay_directory / 'recorded.json').write_text(json.dumps(archives, indent=2))
    return {'image': image, 'version': selected, 'selection': reason, 'has-records': str(bool(records)).lower()}


def main():
    package = ''
    version = ''
    tag = os.environ.get('RELEASE_TAG', '')
    if tag:
        if not tag.startswith('v') or not SEMVER.fullmatch(tag[1:]):
            raise SelectionError('Release tag must be v<semver>.')
        version = tag[1:]
        with open(os.path.join(os.environ.get('BRICK_PATH', '.'), 'package.json')) as stream:
            manifest = json.load(stream)
        package = manifest.get('id', manifest.get('name', ''))
        if not os.environ.get('STORE_TOKEN', ''):
            raise SelectionError('Provenance: release planning requires the namespace store token before building.')
    result = select(os.environ.get('REQUESTED_VERSION', ''), package, version,
                    os.environ.get('STORE_TOKEN', ''), os.environ.get('STORE_URL', 'https://bricks.mass4.org'),
                    os.environ.get('TWIN', 'true') == 'true',
                    replay_directory=Path(os.environ['REPLAY_DIRECTORY']) if os.environ.get('REPLAY_DIRECTORY') else None)
    if output := os.environ.get('GITHUB_OUTPUT'):
        with open(output, 'a') as stream:
            for key, value in result.items():
                stream.write(f'{key}={value}\n')
    message = f'CLI {result["version"]}: `{result["image"]}` ({result["selection"]}).'
    print(message)
    if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(summary, 'a') as stream:
            stream.write(message + '\n')


if __name__ == '__main__':
    try:
        main()
    except (SelectionError, KeyError, TypeError, OSError, ValueError) as error:
        print(f'::error::{error if isinstance(error, SelectionError) else "Image selection failed: invalid configuration or response."}', file=sys.stderr)
        sys.exit(1)
