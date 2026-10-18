import io
import json
import tarfile

import pytest

from vai_backend.pipeline import _ssh, _archive, PipelineError


def test_explicit_port_key_and_legacy_server_options(tmp_path):
    identity = tmp_path / 'project key'
    known_hosts = tmp_path / 'known_hosts'
    identity.write_text('test-only-placeholder')
    known_hosts.write_text('test-only-placeholder')
    args = _ssh({'ssh_host': 'student@course-server', 'ssh_port': 35167,
                 'ssh_identity_file': str(identity), 'ssh_known_hosts_file': str(known_hosts),
                 'ssh_legacy_rsa': True})
    assert args[-1] == 'student@course-server'
    assert args[args.index('-p') + 1] == '35167'
    assert 'IdentityFile=' + str(identity.resolve()) in args
    assert 'UserKnownHostsFile=' + str(known_hosts.resolve()) in args
    assert 'BatchMode=yes' in args and 'StrictHostKeyChecking=yes' in args
    assert 'HostKeyAlgorithms=+ssh-rsa' in args and 'PubkeyAcceptedAlgorithms=+ssh-rsa' in args
    assert not any('ssh-rsa' in arg for arg in _ssh({'ssh_host': 'modern-server'}))


@pytest.mark.parametrize('changes', [
    {'ssh_port': 0}, {'ssh_port': 65536}, {'ssh_port': True}, {'ssh_port': '35167'},
    {'ssh_host': '-bad'}, {'ssh_host': 'server\nother'}, {'ssh_identity_file': 'missing-private-key'},
    {'ssh_legacy_rsa': 'yes'}
])
def test_bad_ssh_settings_rejected(changes):
    with pytest.raises(PipelineError) as error:
        _ssh({'ssh_host': 'school-eda', **changes})
    assert error.value.code == 'CONFIG_ERROR'


def test_worker_archive_does_not_include_local_authentication_settings():
    blob = _archive({}, 'vai_archive_test', {'ssh_host': 'server', 'ssh_identity_file': '/local/key',
                                          'ssh_known_hosts_file': '/local/hosts', 'remote_base': '/data/home/student/vai_runs'})
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as archive:
        payload = json.load(archive.extractfile('input.json'))
    assert payload['config'] == {'remote_base': '/data/home/student/vai_runs'}
