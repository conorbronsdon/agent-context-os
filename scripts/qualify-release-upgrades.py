#!/usr/bin/env python3
"""Qualify exact candidate assets against published baselines and fresh onboarding.

Offline after downloading the published baseline asset sets. Synthetic approval and
fault injection are not human volunteer or native agent evidence. Keep failures.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product', required=True, type=Path)
    parser.add_argument('--assets', required=True, type=Path)
    parser.add_argument('--published-assets', required=True, type=Path)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--bash', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    product, assets, out = args.product.resolve(), args.assets.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=product, text=True).strip() == args.commit
    assert not subprocess.check_output(['git', 'status', '--porcelain=v1', '--untracked-files=all'], cwd=product)
    stem = 'agent-context-os-template-v' + args.version
    provenance = json.loads((assets / (stem + '.provenance.json')).read_text())
    digest = provenance['bundle_lock']['bundle_sha256']
    archive_digest = hashlib.sha256((assets / (stem + '.tar')).read_bytes()).hexdigest()
    assert archive_digest == provenance['archive']['sha256']
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONIOENCODING': 'utf-8'}

    def run(label, command, cwd=product, input=None):
        value = subprocess.run(command, cwd=cwd, env=env, input=input, text=True,
                               encoding='utf-8', capture_output=True, timeout=900)
        (out / (label + '.json')).write_text(json.dumps({
            'command': list(map(str, command)), 'exit': value.returncode,
            'stdout': value.stdout, 'stderr': value.stderr}, indent=2) + '\n', encoding='utf-8')
        assert value.returncode == 0, (label, value.returncode, value.stderr)
        return value.stdout

    run('migration', [sys.executable, str(product / 'scripts/qualify-release-migration.py'),
        '--candidate-assets', str(assets), '--published-assets', str(args.published_assets.resolve()),
        '--expect-commit', args.commit, '--expect-version', args.version,
        '--expect-archive-sha256', archive_digest, '--expect-bundle-sha256', digest,
        '--output', str(out / 'migration')])
    migration = out / 'migration'
    candidate_source = migration / 'candidate' / stem
    # Recovery imports this verified archive directly in parent and crash child.
    # Windows checkout line endings cannot affect the executable qualification.
    baselines = []
    for version in runpy.run_path(str(product / 'scripts/qualify-release-migration.py'))['PUBLISHED']:
        old_stem = 'agent-context-os-template-v' + version
        lock = args.published_assets.resolve() / version / (old_stem + '.bundle.lock.json')
        value = json.loads(lock.read_text())
        baselines.append({'version': version, 'source': str(migration / ('source-' + version) / old_stem),
                          'lock': str(lock), 'sha256': value['bundle_sha256']})
    spec = out / 'published-assets.json'
    spec.write_text(json.dumps(baselines, indent=2) + '\n', encoding='utf-8')
    run('recovery', [sys.executable, str(product / 'scripts/qualify-release-recovery.py'),
        '--product', str(product), '--candidate-source', str(candidate_source),
        '--candidate-lock', str(assets / (stem + '.bundle.lock.json')), '--candidate-sha256', digest,
        '--candidate-commit', args.commit, '--candidate-version', args.version,
        '--old-assets', str(spec), '--out', str(out / 'recovery')])

    workspace = out / 'first-handoff'
    shutil.copytree(candidate_source, workspace)
    run('git-init', ['git', 'init', '--quiet'], cwd=workspace)
    assert Path(subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], cwd=workspace, text=True).strip()).resolve() == workspace
    setup = run('setup', [args.bash, 'scripts/setup.sh', '--agents', 'claude,codex'],
                cwd=workspace, input='y\n\nn\nn\nn\ny\nn\n')
    assert 'Applied the exact reviewed tracked-agent proposal' in setup
    assert subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'], cwd=workspace, capture_output=True).returncode != 0
    payload = {'replace_populated': ['state/current.md'], 'files': {
        'projects/lantern/README.md': '# Lantern\n\nCSV export enables spreadsheet sorting. PDF was rejected. Launch date is unconfirmed.\n',
        'state/current.md': '# Current\n\nLantern needs a CSV column outline. Launch date is unconfirmed.\n'}}
    path = workspace / '.context-os/inputs/lantern-setup.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding='utf-8')
    proposal = json.loads(run('setup-proposal', [sys.executable, '-m', 'contextos', 'propose', 'setup', '--input', str(path)], cwd=workspace))
    proposal_document = json.loads((workspace / proposal['proposal']).read_text())
    assert proposal_document['proposal_digest'] == proposal['proposal_digest']
    (out / 'synthetic-approval.json').write_text(json.dumps({'synthetic': True, 'human_authenticated': False,
        'digest': proposal['proposal_digest'], 'changes': proposal_document['changes']}, indent=2), encoding='utf-8')
    receipt = json.loads(run('setup-apply', [sys.executable, '-m', 'contextos', 'apply', proposal['proposal'],
        '--confirm', proposal['proposal_digest'], '--runtime', 'codex'], cwd=workspace))
    assert receipt['proposal_digest'] == proposal['proposal_digest']
    start = json.loads(run('start', [sys.executable, '-m', 'contextos', 'start'], cwd=workspace))
    assert start['initialized'] is True
    briefing = run('briefing', [sys.executable, '-m', 'contextos', 'start', '--format', 'markdown'], cwd=workspace)
    assert 'Lantern needs a CSV column outline.' in briefing
    report = {'synthetic': True, 'native_host_evidence': False, 'human_volunteer_evidence': False,
              'commit': args.commit, 'version': args.version, 'bundle_sha256': digest,
              'archive_sha256': archive_digest, 'kernel_source': 'verified candidate archive',
              'migration': 'pass', 'recovery': 'pass',
              'release_template_setup_and_initialized_start': 'pass'}
    (out / 'qualification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    if not __debug__:
        raise RuntimeError('Qualification requires assertions enabled')
    main()
