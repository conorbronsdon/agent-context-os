#!/usr/bin/env python3
"""Synthetic migration qualification using exact final release artifacts and real CLI.
No native agent/human evidence. Keeps all fixtures, failed proposals, and receipts.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import time
import traceback

PUBLISHED = {
    '0.14.0': ('4e5db061b45e3ba43f42452c8ef5b6c7627235b9',
               '13d659c8e6f5c5ee44bbfa3aabba7ed58df83b2f27b9f8817b740bb593b7b07b',
               'b014d9fcaff98acc3cc20a67147b4babba1b1eb58b8daab44f301d9543cbf62a'),
    '0.15.0': ('947769c957423919ffcd37d4c83573aea1539bae',
               'c253fc5c56bb5d166e7d925777d67f01418bdcb1cc3594feb07d2525e342381d',
               '7d64abcbb3b80cb722157c34ebe80c8ce42631a6e2fcaf6296e724e8d46b95eb'),
    '1.0.0': ('08b7a76112605c49b287cb2e1b2e29e1f1a0ff35',
              'acaf77cfd6f3e1fecd29366a9317ef404bafc177d754b55cf133f6123e81df79',
              '05d45ccedd597c706ebcad4bd61b37a6d528d42971c7e48509ea85c6a288ccca'),
}

# Published kernels that write schema-2 workspace state themselves.
NATIVE_STATE_BASELINES = {'1.0.0'}

def require(condition, message):
    if not condition:
        raise AssertionError(message)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

def tree(root):
    # Ignore only actual Git metadata and kernel-owned proposal/receipt scratch.
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and p.relative_to(root).parts[0] not in {'.git', '.context-os'}}

def bundle(assets, destination, version, commit, archive_pin, bundle_pin):
    prefix = 'agent-context-os-template-v' + version
    provenance_path = assets / (prefix + '.provenance.json')
    p = json.loads(provenance_path.read_text(encoding='utf-8'))
    lock = assets / (prefix + '.bundle.lock.json')
    archive = assets / (prefix + '.tar')
    sums = {}
    for line in (assets / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        digest, filename = line.split(None, 1)
        sums[filename.strip().lstrip('*')] = digest
    for path in [provenance_path, lock, archive]:
        require(sums.get(path.name) == sha(path), 'SHA256SUMS mismatch: ' + str(path))
    require(sha(archive) == archive_pin == p['archive']['sha256'], 'archive pin mismatch')
    require(sha(lock) == p['bundle_lock']['sha256'], 'provenance lock hash mismatch')
    document = json.loads(lock.read_text(encoding='utf-8'))
    require(p['release']['commit'] == document['bundle']['source_git_commit'] == commit,
            'exact candidate/release commit mismatch')
    require(p['template']['version'] == document['bundle']['version'] == version,
            'exact candidate/release version mismatch')
    require(p['bundle_lock']['bundle_sha256'] == bundle_pin, 'bundle pin mismatch')
    destination.mkdir()
    # Portable safe extraction, including Python 3.10; deny links/special files.
    with tarfile.open(archive) as tf:
        for member in tf.getmembers():
            rel = PurePosixPath(member.name)
            require(not rel.is_absolute() and '..' not in rel.parts and '\\' not in member.name,
                    'unsafe archive member: ' + member.name)
            require(member.isdir() or member.isfile(), 'non-regular archive member: ' + member.name)
            require(rel.parts and rel.parts[0] == p['archive']['root'], 'unexpected archive root')
            if member.isdir():
                (destination / member.name).mkdir(parents=True, exist_ok=True)
            else:
                target = destination / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(member) as input_file:
                    target.write_bytes(input_file.read())
                target.chmod(member.mode & 0o777)
    return {'source': destination / p['archive']['root'], 'lock': lock.resolve(),
            'digest': bundle_pin, 'version': version, 'commit': commit,
            'archive_sha256': archive_pin, 'provenance_sha256': sha(provenance_path)}

class Run:
    def __init__(self, candidate, out):
        self.candidate, self.out, self.sequence = candidate, out, 0
        self.env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONIOENCODING': 'utf-8'}
        # Candidate archive itself is executable authority, never a mutable checkout.
        self.prefix = [sys.executable, '-c',
            'import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module("contextos",run_name="__main__")',
            str(candidate['source']), '--kernel-root', str(candidate['source'])]

    def cli(self, label, *args, success=True, kernel=None, kernel_root=False):
        self.sequence += 1
        before = time.monotonic()
        prefix = self.prefix if kernel is None else [sys.executable, '-c',
            'import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module("contextos",run_name="__main__")',
            str(kernel['source'])] + (['--kernel-root', str(kernel['source'])] if kernel_root else [])
        command = prefix + list(map(str, args))
        result = subprocess.run(command, cwd=self.candidate['source'], env=self.env,
                                capture_output=True, text=True, encoding='utf-8')
        evidence = self.out / ('%03d-%s.json' % (self.sequence, label))
        record = {'command': command, 'elapsed_seconds': time.monotonic() - before,
                  'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
        save(evidence, record)
        require((result.returncode == 0) == success, 'unexpected CLI exit: ' + str(evidence))
        return json.loads(result.stdout) if success else record

    def check(self, b, label):
        return self.cli(label, 'bundle', 'check', '--lock', b['lock'], '--source', b['source'],
                        '--expect-sha256', b['digest'])

    def propose(self, target, b, label, operation='update', profile='full-template', current=None, success=True,
                kernel=None):
        args = ['workspace', operation, '--target', target, '--lock', b['lock'],
                '--source', b['source'], '--expect-sha256', b['digest'], '--agents', 'claude,codex',
                '--profile', profile, '--now', '2026-09-29T12:00:00-07:00']
        if current:
            args += ['--current-lock', current['lock'], '--current-source', current['source'],
                     '--expect-current-sha256', current['digest']]
        return self.cli(label, *args, success=success, kernel=kernel, kernel_root=kernel is not None)

    def apply(self, target, proposal, label, kernel=None):
        path = target / proposal['proposal']
        require(path.is_file(), 'proposal not retained')
        document = json.loads(path.read_text(encoding='utf-8'))
        require(document['proposal_digest'] == proposal['proposal_digest'], 'proposal digest mismatch')
        # Explicitly synthetic review: inspect every proposed change and bind to exact digest.
        save(self.out / (label + '-synthetic-review.json'),
             {'synthetic': True, 'human_authenticated': False,
              'digest': proposal['proposal_digest'], 'changes': document['changes']})
        result = self.cli(label, 'bundle', 'apply', '--target', target, '--proposal', path,
                          '--confirm', proposal['proposal_digest'], '--runtime', 'generic', kernel=kernel,
                          kernel_root=kernel is not None)
        receipt = result.get('receipt', result)
        if isinstance(receipt, dict):
            receipt = receipt.get('receipt')
        require(isinstance(receipt, str) and (target / receipt).is_file(), 'apply receipt missing')
        require(result['proposal_digest'] == proposal['proposal_digest'], 'receipt digest mismatch')
        require(result.get('validation', {}).get('status') != 'fail', 'post-apply doctor failed')
        return result

def fixture(root, old, kind):
    shutil.copytree(old['source'], root)
    result = subprocess.run(['git', '-c', 'core.hooksPath=' + str(root / '.disabled-hooks'),
                             'init', str(root)], capture_output=True, text=True)
    require(result.returncode == 0, 'git init failed: ' + result.stderr)
    require((root / '.git').is_dir(), 'fixture must own its Git metadata')
    config = root / 'contextos.workspace.json'
    config.unlink(missing_ok=True)
    legacy = root / 'workspace.yaml'
    legacy.unlink(missing_ok=True)
    if kind == 'yaml':
        legacy.write_text('state_dir: state\nsessions_dir: sessions\ntask_file: TODO.md\n', encoding='utf-8')
    else:
        save(config, {'schema_version': 1, 'mode': 'full-template', 'agents': ['claude', 'codex'],
             'paths': {'state_dir': 'state', 'sessions_dir': 'sessions', 'task_file': 'TODO.md'},
             'template': {'source': 'agent-context-os-template', 'version': old['version']}})
    personal = {'identity/who-i-am.md': b'# Synthetic identity\nMigration sentinel IDENTITY.\n',
                'state/current.md': b'# Current State\n\n**Last Updated:** 2026-09-29\n\nSynthetic migration sentinel CURRENT.\n',
                'projects/synthetic-migration.md': b'# Synthetic migration\nProject sentinel PROJECT.\n',
                '.agents/skills/synthetic-personal/SKILL.md': b'---\nname: synthetic-personal\ndescription: Test only\n---\n\nPersonal sentinel SKILL.\n'}
    for relative, content in personal.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return personal

def preserved(root, personal):
    for relative, content in personal.items():
        require((root / relative).read_bytes() == content, 'personal content changed: ' + relative)

def state(root, b, profile):
    c = json.loads((root / 'contextos.workspace.json').read_text(encoding='utf-8'))
    require(c['schema_version'] == 2 and c['composition']['profile'] == profile, 'schema/profile mismatch')
    require(c['agents'] == ['claude', 'codex'], 'runtime selection changed')
    require(c['template']['version'] == b['version'] and c['template']['bundle_sha256'] == b['digest'],
            'tracked bundle identity mismatch')
    require(c['paths'] == {'state_dir': 'state', 'sessions_dir': 'sessions', 'task_file': 'TODO.md'},
            'legacy path intent lost')
    require(not (root / 'workspace.yaml').exists(), 'legacy YAML not retired')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-assets', required=True, type=Path)
    parser.add_argument('--published-assets', required=True, type=Path)
    parser.add_argument('--expect-commit', required=True)
    parser.add_argument('--expect-version', required=True)
    parser.add_argument('--expect-archive-sha256', required=True)
    parser.add_argument('--expect-bundle-sha256', required=True)
    parser.add_argument('--output', required=True, type=Path, help='New directory; retained even on failure')
    args = parser.parse_args()
    require(re.fullmatch('[0-9a-f]{40}', args.expect_commit), 'expected commit must be full 40-character SHA')
    require(not args.output.exists(), 'output must not exist; preserve prior evidence')
    args.output.mkdir(parents=True)
    outcome = {'synthetic': True, 'native_runtime_evidence': False, 'human_volunteer_evidence': False,
               'final_release_qualification': args.expect_version == '1.1.1', 'cases': []}
    try:
        candidate = bundle(args.candidate_assets.resolve(), args.output / 'candidate', args.expect_version,
                           args.expect_commit, args.expect_archive_sha256, args.expect_bundle_sha256)
        outcome['candidate'] = {k: str(v) for k, v in candidate.items()}
        run = Run(candidate, args.output)
        run.check(candidate, 'candidate-bundle-check')
        for version, pins in PUBLISHED.items():
            old = bundle(args.published_assets.resolve() / version, args.output / ('source-' + version),
                         version, *pins)
            run.check(old, 'published-' + version + '-bundle-check')
            for kind in ['v1', 'yaml']:
                label = version + '-' + kind
                case = {'id': label, 'status': 'fail'}
                outcome['cases'].append(case)
                try:
                    root = args.output / label
                    personal = fixture(root, old, kind)
                    if kind == 'v1':
                        before = tree(root)
                        error = run.propose(root, old, label + '-direct-selected-refused',
                                            profile='selected', success=False)
                        require('must first preserve the full-template profile' in error['stderr'],
                                'wrong rejection for direct v1 -> selected')
                        require(tree(root) == before, 'rejected direct migration mutated workspace')
                    if kind == 'yaml':
                        # Migrate the existing clone with its verified installed
                        # release before loading a newer kernel. init composes a
                        # fresh workspace and cannot adopt unowned clone files.
                        bridge = run.cli(label + '-legacy-proposal', '--root', root,
                            'workspace', 'propose-migration', '--agents', 'claude,codex',
                            '--now', '2026-09-29T12:00:00-07:00', kernel=old)
                        bridge_path = root / bridge['proposal']
                        bridge_doc = json.loads(bridge_path.read_text(encoding='utf-8'))
                        require(bridge_doc['proposal_digest'] == bridge['proposal_digest'], 'legacy digest mismatch')
                        save(run.out / (label + '-legacy-synthetic-review.json'),
                             {'synthetic': True, 'human_authenticated': False,
                              'digest': bridge['proposal_digest'], 'changes': bridge_doc['changes']})
                        receipt = run.cli(label + '-legacy-apply', '--root', root,
                            'apply', bridge_path, '--confirm', bridge['proposal_digest'],
                            '--runtime', 'generic', kernel=old)
                        require(receipt['proposal_digest'] == bridge['proposal_digest'], 'legacy receipt mismatch')
                        require((root / receipt['receipt']).is_file(), 'legacy receipt missing')
                        require(not (root / 'workspace.yaml').exists(), 'legacy YAML not retired')
                        bridge_config = json.loads((root / 'contextos.workspace.json').read_text())
                        require(bridge_config['schema_version'] == 1 and bridge_config['template']['version'] == old['version'], 'legacy bridge lost installed release identity')
                        preserved(root, personal)
                    proposal = run.propose(root, old, label + '-migrate-full')
                    run.apply(root, proposal, label + '-migrate-full-apply')
                    state(root, old, 'full-template'); preserved(root, personal)
                    proposal = run.propose(root, candidate, label + '-upgrade-final', current=old)
                    run.apply(root, proposal, label + '-upgrade-final-apply')
                    state(root, candidate, 'full-template'); preserved(root, personal)
                    proposal = run.propose(root, candidate, label + '-select-profile', profile='selected')
                    run.apply(root, proposal, label + '-select-profile-apply')
                    state(root, candidate, 'selected'); preserved(root, personal)
                    installed = json.loads((root / '.context-os/installed-bundle.json').read_text(encoding='utf-8'))
                    require(installed['bundle']['sha256'] == candidate['digest'], 'installed pin mismatch')
                    case.update(status='pass', final_sources=tree(root), preserved_paths=sorted(personal))
                except Exception as exc:
                    case.update(error=str(exc), traceback=traceback.format_exc())
            for profile in (['full-template', 'selected'] if version in NATIVE_STATE_BASELINES else []):
                # The published kernel itself migrates and installs the workspace,
                # so the candidate upgrades state it did not write (#246).
                label = version + '-native-' + profile
                case = {'id': label, 'status': 'fail'}
                outcome['cases'].append(case)
                try:
                    root = args.output / label
                    personal = fixture(root, old, 'v1')
                    proposal = run.propose(root, old, label + '-old-migrate', kernel=old)
                    run.apply(root, proposal, label + '-old-migrate-apply', kernel=old)
                    if profile == 'selected':
                        proposal = run.propose(root, old, label + '-old-select', profile='selected', kernel=old)
                        run.apply(root, proposal, label + '-old-select-apply', kernel=old)
                    state(root, old, profile); preserved(root, personal)
                    installed = json.loads((root / '.context-os/installed-bundle.json').read_text(encoding='utf-8'))
                    require(installed['bundle']['sha256'] == old['digest'], 'published kernel did not install its bundle')
                    proposal = run.propose(root, candidate, label + '-upgrade', profile=profile, current=old)
                    run.apply(root, proposal, label + '-upgrade-apply')
                    state(root, candidate, profile); preserved(root, personal)
                    installed = json.loads((root / '.context-os/installed-bundle.json').read_text(encoding='utf-8'))
                    require(installed['bundle']['sha256'] == candidate['digest'], 'installed pin mismatch')
                    case.update(status='pass', final_sources=tree(root), preserved_paths=sorted(personal))
                except Exception as exc:
                    case.update(error=str(exc), traceback=traceback.format_exc())
            for managed in ['AGENTS.md', '.agents/skills/context-end/SKILL.md']:
                label = version + '-conflict-' + ('agents' if managed == 'AGENTS.md' else 'skill')
                case = {'id': label, 'status': 'fail'}
                outcome['cases'].append(case)
                try:
                    root = args.output / label
                    personal = fixture(root, old, 'v1')
                    with (root / managed).open('ab') as file:
                        file.write(b'\nSynthetic personalized managed conflict sentinel.\n')
                    before = tree(root)
                    error = run.propose(root, old, label + '-rejected', success=False)
                    require(managed in error['stderr'] and any(word in error['stderr'].lower() for word in ['collides', 'dirty', 'conflict']), 'managed conflict rejection not identified')
                    require(tree(root) == before, 'managed conflict refusal mutated sources')
                    preserved(root, personal)
                    case.update(status='pass', conflicting_path=managed, before=before,
                                after=tree(root), error_evidence=error['stderr'])
                except Exception as exc:
                    case.update(error=str(exc), traceback=traceback.format_exc())
        outcome['status'] = 'pass' if all(c['status'] == 'pass' for c in outcome['cases']) else 'fail'
    except Exception as exc:
        outcome.update(status='fail', error=str(exc), traceback=traceback.format_exc())
    save(args.output / 'qualification-migration-result.json', outcome)
    print(json.dumps({'status': outcome['status'], 'cases': [(c['id'], c['status']) for c in outcome['cases']],
                      'evidence': str(args.output.resolve())}, indent=2))
    return 0 if outcome['status'] == 'pass' else 1

if __name__ == '__main__':
    if not __debug__:
        raise RuntimeError('Qualification requires assertions enabled')
    sys.exit(main())
